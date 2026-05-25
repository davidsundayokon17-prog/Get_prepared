import os, hmac, hashlib, uuid, random, string, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from flask import Flask, request, jsonify, abort
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)
CORS(app)

app.config["SQLALCHEMY_DATABASE_URI"]        = os.getenv("DATABASE_URL", "sqlite:///getprepared.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

PAYSTACK_PUBLIC_KEY     = os.getenv("pk_live_10facb7256c431e6120390bc7c6a18a7cca7663f", "")
PAYSTACK_SECRET_KEY     = os.getenv("sk_live_5c757b451f0a616b7f0f462b54feb0d9a116d090", "")
PAYSTACK_WEBHOOK_SECRET = os.getenv("sk_live_5c757b451f0a616b7f0f462b54feb0d9a116d090", "")
APP_SECRET              = os.getenv("APP_SECRET", "getprepared2024admin")

# !! CHANGE PRICE HERE IN FUTURE !!
# Just update ACTIVATION_PRICE_KOBO in Railway environment variables
# e.g. N1000 = 100000, N1500 = 150000, N2000 = 200000
ACTIVATION_PRICE_KOBO = int(os.getenv("ACTIVATION_PRICE_KOBO", "80000"))

# Email config (uses Gmail SMTP - free)
GMAIL_ADDRESS  = os.getenv("davidsundayokon17@gmail.com", "")   # your gmail
GMAIL_PASSWORD = os.getenv("sktn bayg nque lhrz", "")  # gmail app password

# WhatsApp number for support
WHATSAPP_NUMBER = os.getenv("WHATSAPP_NUMBER", "2349067990327")

db      = SQLAlchemy(app)
limiter = Limiter(get_remote_address, app=app, default_limits=["200 per day"])

# ── MODELS ───────────────────────────────────────────────────────────────────
class Payment(db.Model):
    __tablename__  = "payments"
    id             = db.Column(db.Integer, primary_key=True)
    reference      = db.Column(db.String(100), unique=True, nullable=False)
    email          = db.Column(db.String(200), nullable=True)
    phone          = db.Column(db.String(20),  nullable=True)
    name           = db.Column(db.String(200), nullable=True)
    amount_kobo    = db.Column(db.Integer, nullable=False)
    status         = db.Column(db.String(20), default="pending")
    confirmed_at   = db.Column(db.DateTime, nullable=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    activation     = db.relationship("ActivationCode", backref="payment", uselist=False)

class ActivationCode(db.Model):
    __tablename__  = "activation_codes"
    id             = db.Column(db.Integer, primary_key=True)
    code           = db.Column(db.String(50), unique=True, nullable=False)
    payment_id     = db.Column(db.Integer, db.ForeignKey("payments.id"))
    is_used        = db.Column(db.Boolean, default=False)
    device_id      = db.Column(db.String(200), nullable=True)
    activated_at   = db.Column(db.DateTime, nullable=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

class ReferralPayout(db.Model):
    __tablename__  = "referral_payouts"
    id             = db.Column(db.Integer, primary_key=True)
    referral_code  = db.Column(db.String(50), unique=True, nullable=False)
    name           = db.Column(db.String(200), nullable=True)
    phone          = db.Column(db.String(20),  nullable=True)
    bank_name      = db.Column(db.String(100), nullable=True)
    account_number = db.Column(db.String(20),  nullable=True)
    account_name   = db.Column(db.String(200), nullable=True)
    amount         = db.Column(db.Integer, default=10)
    status         = db.Column(db.String(20), default="pending")
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at        = db.Column(db.DateTime, nullable=True)

# ── HELPERS ───────────────────────────────────────────────────────────────────
def generate_activation_code():
    chars    = string.ascii_uppercase + string.digits
    segments = ["".join(random.choices(chars, k=4)) for _ in range(3)]
    return "-".join(segments)

def verify_paystack_signature(payload, signature):
    expected = hmac.new(
        PAYSTACK_WEBHOOK_SECRET.encode("utf-8"),
        payload,
        hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(expected, signature)

def send_code_to_user(email, phone, code, name="Student"):
    price_naira = ACTIVATION_PRICE_KOBO // 100
    print(f"[NOTIFY] Code={code} Email={email} Phone={phone} Name={name}")

    # Send email if Gmail is configured
    if GMAIL_ADDRESS and GMAIL_PASSWORD and email:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = "Your Get Prepared Activation Code"
            msg["From"]    = f"Get Prepared <{GMAIL_ADDRESS}>"
            msg["To"]      = email

            html = f"""
<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;background:#0B0F1A;color:#fff;padding:20px">
  <div style="max-width:500px;margin:0 auto;background:#151d2e;border-radius:16px;padding:30px;border:1px solid #1e2d45">
    <div style="text-align:center;margin-bottom:24px">
      <div style="width:70px;height:70px;border-radius:16px;background:#00B4C8;color:#0B0F1A;font-size:24px;font-weight:900;display:inline-flex;align-items:center;justify-content:center">GP</div>
      <h1 style="color:#00E5A0;margin:12px 0 4px">Get Prepared</h1>
      <p style="color:#8899bb;margin:0">Nigeria's #1 CBT & Study App</p>
    </div>
    <p style="color:#f0f4ff">Hello <strong>{name}</strong>! 🎉</p>
    <p style="color:#8899bb">Your payment of <strong style="color:#00E5A0">₦{price_naira}</strong> has been confirmed. Here is your activation code:</p>
    <div style="background:#0B0F1A;border:2px solid #00E5A0;border-radius:12px;padding:20px;text-align:center;margin:20px 0">
      <div style="font-size:28px;font-weight:900;color:#00E5A0;letter-spacing:6px">{code}</div>
    </div>
    <p style="color:#8899bb">Steps to activate:</p>
    <ol style="color:#8899bb;line-height:2">
      <li>Go to <a href="https://getprepared2.netlify.app" style="color:#00E5A0">getprepared2.netlify.app</a></li>
      <li>Tap <strong style="color:#fff">"Already have a code?"</strong></li>
      <li>Enter the code above</li>
      <li>Start studying! 📚</li>
    </ol>
    <div style="background:#1a2235;border-radius:8px;padding:12px;margin-top:20px;font-size:13px;color:#8899bb">
      Need help? WhatsApp us: <a href="https://wa.me/{WHATSAPP_NUMBER}" style="color:#00E5A0">+{WHATSAPP_NUMBER}</a>
    </div>
    <p style="color:#4a5a7a;font-size:12px;margin-top:20px;text-align:center">Get Prepared — WAEC · JAMB · NECO · NABTEB</p>
  </div>
</body>
</html>"""

            text = f"""Hello {name}!

Your Get Prepared activation code is: {code}

Steps to activate:
1. Go to getprepared2.netlify.app
2. Tap "Already have a code?"
3. Enter: {code}
4. Start studying!

Need help? WhatsApp: +{WHATSAPP_NUMBER}

— Get Prepared Team"""

            msg.attach(MIMEText(text, "plain"))
            msg.attach(MIMEText(html, "html"))

            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(GMAIL_ADDRESS, GMAIL_PASSWORD)
                server.sendmail(GMAIL_ADDRESS, email, msg.as_string())
            print(f"[EMAIL] Sent to {email}")
        except Exception as e:
            print(f"[EMAIL ERROR] {e}")

# ── ROUTES ────────────────────────────────────────────────────────────────────
@app.route("/health")
def health():
    price_naira = ACTIVATION_PRICE_KOBO // 100
    return jsonify({
        "status":  "ok",
        "app":     "Get Prepared Backend",
        "price":   f"NGN {price_naira}",
        "version": "3.0"
    })

@app.route("/api/payment/initiate", methods=["POST"])
@limiter.limit("10 per hour")
def initiate_payment():
    data  = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    phone = data.get("phone", "").strip()
    name  = data.get("name",  "").strip()

    if not email:
        return jsonify({"error": "email required"}), 400

    reference = f"GP-{uuid.uuid4().hex[:12].upper()}"
    payment   = Payment(
        reference   = reference,
        email       = email,
        phone       = phone,
        name        = name,
        amount_kobo = ACTIVATION_PRICE_KOBO,
        status      = "pending"
    )
    db.session.add(payment)
    db.session.commit()

    return jsonify({
        "status":    "ok",
        "reference": reference,
        "amount":    ACTIVATION_PRICE_KOBO,
        "email":     email
    }), 200

@app.route("/api/webhook/paystack", methods=["POST"])
def paystack_webhook():
    payload   = request.get_data()
    signature = request.headers.get("x-paystack-signature", "")

    if not verify_paystack_signature(payload, signature):
        return jsonify({"error": "Invalid signature"}), 400

    event      = request.get_json()
    event_type = event.get("event", "")
    print(f"[WEBHOOK] {event_type}")

    if event_type == "charge.success":
        data      = event.get("data", {})
        reference = data.get("reference", "")
        amount    = data.get("amount", 0)
        email     = data.get("customer", {}).get("email", "")
        phone     = data.get("metadata", {}).get("phone", "")
        name      = data.get("metadata", {}).get("name", "Student")

        payment = Payment.query.filter_by(reference=reference).first()

        if payment and payment.status == "already processed":
            return jsonify({"status": "already processed"}), 200

        if amount < ACTIVATION_PRICE_KOBO:
            if payment:
                payment.status = "failed"
                db.session.commit()
            return jsonify({"error": "Insufficient amount"}), 400

        if not payment:
            payment = Payment(
                reference   = reference,
                email       = email,
                phone       = phone,
                name        = name,
                amount_kobo = amount,
                status      = "pending"
            )
            db.session.add(payment)
            db.session.flush()

        payment.status       = "success"
        payment.confirmed_at = datetime.now(timezone.utc)

        code = generate_activation_code()
        while ActivationCode.query.filter_by(code=code).first():
            code = generate_activation_code()

        activation = ActivationCode(code=code, payment_id=payment.id)
        db.session.add(activation)
        db.session.commit()

        send_code_to_user(
            email = payment.email or email,
            phone = payment.phone or phone,
            name  = payment.name  or name,
            code  = code
        )

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
        resp["code"]        = payment.activation.code
    return jsonify(resp)

@app.route("/api/activate", methods=["POST"])
@limiter.limit("5 per hour")
def activate_device():
    data      = request.get_json(silent=True) or {}
    code      = data.get("code", "").strip().upper()
    device_id = data.get("device_id", "").strip()

    if not code or not device_id:
        return jsonify({"error": "code and device_id required"}), 400

    activation = ActivationCode.query.filter_by(code=code).first()
    if not activation:
        return jsonify({"error": "Invalid activation code"}), 404

    if activation.is_used and activation.device_id != device_id:
        return jsonify({"error": "Code already used on another device"}), 403

    if activation.is_used and activation.device_id == device_id:
        return jsonify({"status": "already_activated", "message": "Welcome back!"}), 200

    activation.is_used      = True
    activation.device_id    = device_id
    activation.activated_at = datetime.now(timezone.utc)
    db.session.commit()

    return jsonify({
        "status":  "activated",
        "message": "Welcome to Get Prepared! 🎉"
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

@app.route("/referral/register", methods=["POST"])
def referral_register():
    data  = request.get_json(silent=True) or {}
    code  = data.get("referralCode", "").strip()
    name  = data.get("newUserName",  "").strip()
    phone = data.get("newUserPhone", "").strip()
    if not code:
        return jsonify({"status": "ok"})
    existing = ReferralPayout.query.filter_by(referral_code=code).first()
    if not existing:
        db.session.add(ReferralPayout(
            referral_code=code, name=name, phone=phone, status="registered"
        ))
        db.session.commit()
    return jsonify({"status": "ok"})

@app.route("/referral/payout", methods=["POST"])
def referral_payout():
    data   = request.get_json(silent=True) or {}
    code   = data.get("referralCode", "").strip()
    amount = data.get("amount", 10)
    if not code:
        return jsonify({"status": "ok"})
    existing = ReferralPayout.query.filter_by(referral_code=code).first()
    if existing:
        existing.status = "pending"
        existing.amount = amount
    else:
        db.session.add(ReferralPayout(
            referral_code=code, amount=amount, status="pending"
        ))
    db.session.commit()
    return jsonify({"status": "ok"})

@app.route("/referral/bank-details", methods=["POST"])
def save_bank_details():
    data    = request.get_json(silent=True) or {}
    code    = data.get("referralCode",  "").strip()
    bank    = data.get("bankName",      "").strip()
    account = data.get("accountNumber", "").strip()
    accname = data.get("accountName",   "").strip()
    if not code:
        return jsonify({"status": "ok"})
    existing = ReferralPayout.query.filter_by(referral_code=code).first()
    if existing:
        existing.bank_name      = bank
        existing.account_number = account
        existing.account_name   = accname
        db.session.commit()
    return jsonify({"status": "ok"})

@app.route("/api/admin/stats", methods=["GET"])
def admin_stats():
    if request.headers.get("X-Admin-Secret") != APP_SECRET:
        abort(403)
    pending  = ReferralPayout.query.filter_by(status="pending").all()
    codes    = ActivationCode.query.order_by(ActivationCode.created_at.desc()).limit(20).all()
    price_naira = ACTIVATION_PRICE_KOBO // 100
    total    = ActivationCode.query.count()
    return jsonify({
        "totalUsers":     total,
        "totalReferrals": ReferralPayout.query.count(),
        "pendingPayouts": len(pending),
        "currentPrice":   f"N{price_naira}",
        "totalRevenue":   total * price_naira,
        "pendingPayoutsList": [{
            "id":            p.referral_code,
            "referralCode":  p.referral_code,
            "name":          p.name,
            "phone":         p.phone,
            "bankName":      p.bank_name,
            "accountNumber": p.account_number,
            "accountName":   p.account_name,
            "amount":        p.amount,
            "status":        p.status
        } for p in pending],
        "recentActivations": [{
            "code":         c.code,
            "is_used":      c.is_used,
            "device_id":    c.device_id,
            "name":         c.payment.name   if c.payment else "",
            "email":        c.payment.email  if c.payment else "",
            "phone":        c.payment.phone  if c.payment else "",
            "date":         c.created_at.isoformat() if c.created_at else "",
            "activated_at": c.activated_at.isoformat() if c.activated_at else "",
            "method":       "Manual" if c.payment and "MANUAL" in (c.payment.reference or "") else "Paystack"
        } for c in codes]
    })

@app.route("/api/admin/mark-paid", methods=["POST"])
def mark_paid():
    if request.headers.get("X-Admin-Secret") != APP_SECRET:
        abort(403)
    data = request.get_json(silent=True) or {}
    code = data.get("id", "").strip()
    p    = ReferralPayout.query.filter_by(referral_code=code).first()
    if p:
        p.status  = "paid"
        p.paid_at = datetime.now(timezone.utc)
        db.session.commit()
    return jsonify({"status": "ok"})

@app.route("/api/admin/issue-code", methods=["POST"])
def admin_issue_code():
    data  = request.get_json(silent=True) or {}
    if data.get("secret") != APP_SECRET:
        abort(403)
    email = data.get("email", "").strip().lower()
    phone = data.get("phone", "").strip()
    name  = data.get("name",  "Student").strip()
    if not email and not phone:
        return jsonify({"error": "email or phone required"}), 400

    reference = f"MANUAL-{uuid.uuid4().hex[:8].upper()}"
    payment   = Payment(
        reference   = reference,
        email       = email,
        phone       = phone,
        name        = name,
        amount_kobo = ACTIVATION_PRICE_KOBO,
        status      = "success",
        confirmed_at= datetime.now(timezone.utc)
    )
    db.session.add(payment)
    db.session.flush()

    code = generate_activation_code()
    while ActivationCode.query.filter_by(code=code).first():
        code = generate_activation_code()

    db.session.add(ActivationCode(code=code, payment_id=payment.id))
    db.session.commit()

    send_code_to_user(email=email, phone=phone, name=name, code=code)
    return jsonify({"status": "ok", "code": code})

@app.route("/api/admin/activations", methods=["GET"])
def admin_list():
    if request.headers.get("X-Admin-Secret") != APP_SECRET:
        abort(403)
    codes = ActivationCode.query.order_by(
        ActivationCode.created_at.desc()).limit(50).all()
    return jsonify([{
        "code":         c.code,
        "is_used":      c.is_used,
        "device_id":    c.device_id,
        "created_at":   c.created_at.isoformat() if c.created_at else "",
        "activated_at": c.activated_at.isoformat() if c.activated_at else "",
        "email":        c.payment.email if c.payment else "",
        "name":         c.payment.name  if c.payment else "",
    } for c in codes])

@app.route("/api/admin/set-price", methods=["POST"])
def set_price():
    if request.headers.get("X-Admin-Secret") != APP_SECRET:
        abort(403)
    data        = request.get_json(silent=True) or {}
    new_price   = int(data.get("priceNaira", 800))
    global ACTIVATION_PRICE_KOBO
    ACTIVATION_PRICE_KOBO = new_price * 100
    return jsonify({
        "status":    "ok",
        "new_price": f"N{new_price}",
        "note":      "Also update ACTIVATION_PRICE_KOBO in Railway env vars to make permanent"
    })

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
