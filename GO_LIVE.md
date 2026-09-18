# نقشه کارهایی که فقط خودت می‌توانی انجام بدهی
# (خارج از توان Cloud Agent)

این فایل کارهایی است که با کد حل نمی‌شود. Agent کد، تست، Docker و مسیر پرداخت را آماده کرده؛
موارد زیر باید توسط تو / حساب‌های واقعی انجام شود.

## 1) اکانت و هویت
- [ ] ساخت حساب Stripe (ترجیحاً شرکتی)
- [ ] تکمیل KYC / هویت کسب‌وکار در Stripe تا بتوانی پول واقعی بگیری
- [ ] اگر مخاطب ایران است: بررسی کن Stripe به کشور/حساب بانکی‌ات سرویس می‌دهد یا نه
      - اگر نه: باید PSP جایگزین (یا فروش آفلاین + assign پلن دستی) انتخاب کنی

## 2) کلیدهای Stripe (Test اول، بعد Live)
در Stripe Dashboard:
- [ ] Products بساز: MemoryBridge Starter ($49/mo) و Growth ($199/mo)
- [ ] برای هر کدام یک recurring Price بساز و `price_...` را کپی کن
- [ ] Developers → API keys → `sk_test_...` (بعداً `sk_live_...`)
- [ ] Developers → Webhooks → endpoint:
      `https://YOUR_DOMAIN/v1/billing/webhook`
      events: `checkout.session.completed`, `customer.subscription.deleted`
- [ ] `whsec_...` را کپی کن

داخل `.env` روی سرور:
```
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_STARTER=price_...
STRIPE_PRICE_GROWTH=price_...
PUBLIC_BASE_URL=https://YOUR_DOMAIN
BILLING_SUCCESS_URL=https://YOUR_DOMAIN/billing/success
BILLING_CANCEL_URL=https://YOUR_DOMAIN/billing/cancel
```

## 3) سرور و دامنه
- [ ] خرید/تنظیم دامنه (مثلاً memorybridge.example)
- [ ] VPS یا PaaS (Fly/Render/Railway/AWS/…) با Docker
- [ ] DNS → سرور
- [ ] TLS/HTTPS (Caddy/Nginx/Cloudflare)
- [ ] Postgres پایدار + بکاپ خودکار
- [ ] Secrets را در platform secrets بگذار (نه داخل git)

تولید کلیدهای خود MemoryBridge:
```bash
python3 -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"  # ENCRYPTION_KEY
python3 -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"  # TOKEN_HASH_PEPPER
python3 -c "import secrets; print('mbs_' + secrets.token_urlsafe(32))"  # SERVICE_API_KEYS bootstrap
python3 -c "import secrets; print('mba_' + secrets.token_urlsafe(32))"  # ADMIN_API_KEY
```

دیپلوی سریع با Docker Compose (روی سرور):
```bash
cp .env.example .env   # پر کن
docker compose up -d --build
```

## 4) پول و حقوقی
- [ ] حساب بانکی متصل به Stripe
- [ ] تصمیم مجوز/شرکت/مالیات
- [ ] انتخاب License برای ریپو (الان license ندارد)
- [ ] ایمیل واقعی پشتیبانی/فروش (نه placeholder)
- [ ] Privacy Policy + Terms (برای فروش جدی لازم است)

## 5) فروش
- [ ] یک مشتری آزمایشی واقعی بگیر
- [ ] با کارت تست Stripe یک خرید Starter بزن و webhook را چک کن
- [ ] بعد از سبز شدن test mode → کلیدهای live را جایگزین کن
- [ ] قیمت/پیام سایت را اگر بازارت ایران/منطقه است بومی‌سازی کن

## آنچه Agent دیگر نمی‌تواند به‌جای تو انجام دهد
1. ساخت/تأیید اکانت Stripe و دریافت پول واقعی  
2. خرید دامنه و اتصال DNS  
3. پرداخت هزینه سرور ابری  
4. دسترسی به کارت بانکی / KYC  
5. امضای قرارداد حقوقی و مالیات  
6. پیدا کردن و بستن اولین مشتری واقعی  

اگر این ۶ مورد را انجام بدهی، محصول از نظر فنی آماده گرفتن پول است.
