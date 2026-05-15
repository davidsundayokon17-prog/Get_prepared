import os, hmac, hashlib, uuid, random, string
from datetime import datetime, timezone
from flask import Flask, request, jsonify, abort
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)
CORS(app)

app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///get_prepared.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

PAYSTACK_PUBLIC_KEY     = os.getenv("PAYSTACK_PUBLIC_KEY", "pk_live_10facb7256c431e6120390bc7c6a18a7cca7663f")
PAYSTACK_SECRET_KEY     = os.getenv("PAYSTACK_SECRET_KEY", "sk_live_5c757b451f0a616b7f0f462b54feb0d9a116d090")
PAYSTACK_WEBHOOK_SECRET = os.getenv("PAYSTACK_WEBHOOK_SECRET", "GetPrepared2025Webhook")
ACTIVATION_PRICE_KOBO   = 80000
APP_SECRET              = os.getenv("APP_SECRET", "SundayGetPrepared2025")

db      = SQLAlchemy(app)
limiter = Limiter(get_remote_address, app=app, default_limits=["200 per day", "50 per hour"])

class Payment(db.Model):
    __tablename__ = "payments"
    id           = db.Column(db.Integer, primary_key=True)
    reference    = db.Column(db.String(100), unique=True, nullable=False)
    email        = db.Column(db.String(200), nullable=False)
    phone        = db.Column(db.String(20), nullable=True)
    amount_kobo  = db.Column(db.Integer, nullable=False)
    status       = db.Column(db.String(20), default="pending")
    created_at   = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    confirmed_at = db.Column(db.DateTime, nullable=True)
    activation   = db.relationship("ActivationCode", backref="payment", uselist=False)

class ActivationCode(db.Model):
    __tablename__  = "activation_codes"
    id             = db.Column(db.Integer, primary_key=True)
    code           = db.Column(db.String(20), unique=True, nullable=False)
    payment_id     = db.Column(db.Integer, db.ForeignKey("payments.id"), nullable=False)
    device_id      = db.Column(db.String(200), nullable=True)
    is_used        = db.Column(db.Boolean, default=False)
    created_at     = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    activated_at   = db.Column(db.DateTime, nullable=True)

def generate_activation_code():
    chars = string.ascii_uppercase + string.digits
    segments = ["".join(random.choices(chars, k=4)) for _ in range(4)]
    return "-".join(segments)

def verify_paystack_signature(payload, signature):
    expected = hmac.new(
        PAYSTACK_WEBHOOK_SECRET.encode("utf-8"),
        payload, hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(expected, signature)

def send_code_to_user(email, phone, code):
    print(f"[NOTIFY] Code={code} Email={email} Phone={phone}")

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "app": "Get Prepared Backend",
        "price": "NGN 800",
        "version": "2.0"
    })

@app.route("/api/payment/initiate", methods=["POST"])
@limiter.limit("10 per hour")
def initiate_payment():
    data      = request.get_json(silent=True) or {}
    email     = data.get("email", "").strip().lower()
    phone     = data.get("phone", "").strip()
    if not email or "@" not in email:
        return jsonify({"error": "Valid email required"}), 400
    reference = f"GP-{uuid.uuid4().hex[:12].upper()}"
    payment   = Payment(reference=reference, email=email, phone=phone,
                        amount_kobo=ACTIVATION_PRICE_KOBO, status="pending")
    db.session.add(payment)
    db.session.commit()
    import urllib.request, json as _json
    payload = _json.dumps({
        "email": email,
        "amount": ACTIVATION_PRICE_KOBO,
        "reference": reference,
        "currency": "NGN",
        "metadata": {"phone": phone},
        "callback_url": os.getenv("APP_CALLBACK_URL",
                        "https://getprepared.netlify.app/callback.html"),
    }).encode()
    req = urllib.request.Request(
        "https://api.paystack.co/transaction/initialize", data=payload,
        headers={"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            result = _json.loads(resp.read())
        return jsonify({
            "authorization_url": result["data"]["authorization_url"],
            "reference": reference,
            "public_key": PAYSTACK_PUBLIC_KEY,
        })
    except Exception as e:
        return jsonify({"error": "Paystack error", "detail": str(e)}), 502

@app.route("/api/webhook/paystack", methods=["POST"])
def paystack_webhook():
    signature = request.headers.get("x-paystack-signature", "")
    payload   = request.get_data()
    if not verify_paystack_signature(payload, signature):
        abort(401)
    import json as _json
    event     = _json.loads(payload)
    if event.get("event") != "charge.success":
        return jsonify({"status": "ignored"}), 200
    data      = event["data"]
    reference = data.get("reference")
    amount    = data.get("amount", 0)
    payment   = Payment.query.filter_by(reference=reference).first()
    if not payment:
        return jsonify({"error": "Payment not found"}), 404
    if payment.status == "success":
        return jsonify({"status": "already processed"}), 200
    if amount < ACTIVATION_PRICE_KOBO:
        payment.status = "failed"
        db.session.commit()
        return jsonify({"error": "Insufficient amount"}), 400
    payment.status       = "success"
    payment.confirmed_at = datetime.now(timezone.utc)
    code = generate_activation_code()
    while ActivationCode.query.filter_by(code=code).first():
        code = generate_activation_code()
    activation = ActivationCode(code=code, payment_id=payment.id)
    db.session.add(activation)
    db.session.commit()
    send_code_to_user(
        email=payment.email,
        phone=payment.phone or data.get("metadata", {}).get("phone", ""),
        code=code)
    return jsonify({"status": "ok"}), 200

@app.route("/api/payment/status/<reference>", methods=["GET"])
@limiter.limit("30 per minute")
def payment_status(reference):
    payment = Payment.query.filter_by(reference=reference).first()
    if not payment:
        return jsonify({"error": "Not found"}), 404
    resp = {"status": payment.status}
    if payment.status == "success" and payment.activation:
        resp["code_issued"] = True
    return jsonify(resp)

@app.route("/api/activate", methods=["POST"])
@limiter.limit("5 per hour")
def activate_device():
    data      = request.get_json(silent=True) or {}
    code      = data.get("code", "").strip().upper()
    device_id = data.get("device_id", "").strip()
    if not code or not device_id:
        return jsonify({"error": "code and device_id are required"}), 400
    activation = ActivationCode.query.filter_by(code=code).first()
    if not activation:
        return jsonify({"error": "Invalid activation code"}), 404
    if activation.is_used and activation.device_id != device_id:
        return jsonify({"error": "Code already used on another device"}), 403
    if activation.is_used and activation.device_id == device_id:
        return jsonify({"status": "already_activated"}), 200
    activation.is_used      = True
    activation.device_id    = device_id
    activation.activated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({
        "status": "activated",
        "message": "Welcome to Get Prepared! Lifetime access unlocked."
    }), 200

@app.route("/api/activation/check", methods=["POST"])
@limiter.limit("60 per hour")
def check_activation():
    data      = request.get_json(silent=True) or {}
    device_id = data.get("device_id", "").strip()
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    activation = ActivationCode.query.filter_by(
        device_id=device_id, is_used=True).first()
    return jsonify({"activated": bool(activation)})

@app.route("/api/admin/issue-code", methods=["POST"])
def admin_issue_code():
    data = request.get_json(silent=True) or {}
    if data.get("secret") != APP_SECRET:
        abort(403)
    email = data.get("email", "").strip().lower()
    phone = data.get("phone", "").strip()
    if not email:
        return jsonify({"error": "email required"}), 400
    reference = f"MANUAL-{uuid.uuid4().hex[:10].upper()}"
    payment   = Payment(reference=reference, email=email, phone=phone,
                        amount_kobo=ACTIVATION_PRICE_KOBO, status="success",
                        confirmed_at=datetime.now(timezone.utc))
    db.session.add(payment)
    db.session.flush()
    code = generate_activation_code()
    while ActivationCode.query.filter_by(code=code).first():
        code = generate_activation_code()
    db.session.add(ActivationCode(code=code, payment_id=payment.id))
    db.session.commit()
    send_code_to_user(email=email, phone=phone, code=code)
    return jsonify({"status": "ok", "code": code, "reference": reference})

@app.route("/api/admin/activations", methods=["GET"])
def admin_list():
    if request.headers.get("X-Admin-Secret", "") != APP_SECRET:
        abort(403)
    codes = ActivationCode.query.order_by(
        ActivationCode.created_at.desc()).limit(100).all()
    return jsonify([{
        "code":         c.code,
        "is_used":      c.is_used,
        "device_id":    c.device_id,
        "created_at":   c.created_at.isoformat(),
        "activated_at": c.activated_at.isoformat() if c.activated_at else None,
        "email":        c.payment.email,
    } for c in codes])

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
