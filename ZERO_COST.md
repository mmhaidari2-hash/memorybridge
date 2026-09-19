# مسیر صفر هزینه (بدون سرور ماهانه / بدون Stripe)

هدف: MemoryBridge را بفروشی و پول بگیری، بدون هزینه ماهانه.

ایده اصلی:
- محصول را روی لپ‌تاپ یا یک ماشین رایگان موقت اجرا کن
- مشتری را دستی پیدا کن
- پول را آفلاین بگیر (کارت‌به‌کارت / بانک / Wise)
- پلن را با Admin API دستی باز کن

---

## مرحله 0 — آماده‌سازی لپ‌تاپ (رایگان)

1. Node.js و Python 3.11+ را نصب کن
2. ریپو را بگیر:

```bash
git clone https://github.com/mmhaidari2-hash/memorybridge.git
cd memorybridge
git checkout cursor/v04-commercial-foundation-9c9c
```

3. محیط را بساز:

```bash
cp .env.example .env
```

حداقل این‌ها را در `.env` پر کن (مقادیر تصادفی قوی):

```bash
python3 -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
python3 -c "import secrets; print('mbs_' + secrets.token_urlsafe(32))"
python3 -c "import secrets; print('mba_' + secrets.token_urlsafe(32))"
```

برای شروع بدون Postgres:

```env
DATABASE_URL=sqlite:///./memorybridge.db
ENCRYPTION_KEY=...
TOKEN_HASH_PEPPER=...
SERVICE_API_KEYS=mbs_...
ADMIN_API_KEY=mba_...
PUBLIC_BASE_URL=http://localhost:8000
```

4. نصب و اجرا:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
cd web && npm install && npm run build && cd ..
uvicorn main:app --host 0.0.0.0 --port 8000
```

باز کن: http://localhost:8000

سایت + API روی همین آدرس است.

---

## مرحله 1 — دمو به مشتری (رایگان)

به مشتری نشان بده:
1. صفحه قیمت‌ها
2. ساخت tenant رایگان از سایت
3. یک store/recall ساده با API key

اسکریپت سریع تست:

```bash
curl -s http://localhost:8000/v1/billing/plans
```

یا از مودال سایت: Create tenant → Free.

---

## مرحله 2 — فروش آفلاین (بدون Stripe)

پیشنهاد قیمت همان پلن‌ها:
- Free: £0
- Starter: £49 / ماه
- Growth: £199 / ماه

روش دریافت پول:
- کارت‌به‌کارت / انتقال بانکی
- Wise / Revolut (اگر داری)
- فاکتور ساده PDF

بعد از دریافت پول، پلن را دستی باز کن:

```bash
# 1) tenant بساز (اگر از قبل نیست)
curl -X POST http://localhost:8000/v1/admin/tenants \
  -H "X-MemoryBridge-Admin-Key: mba_YOUR_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"Acme AI","slug":"acme-ai"}'

# 2) کلید بده
curl -X POST http://localhost:8000/v1/admin/tenants/TENANT_ID/keys \
  -H "X-MemoryBridge-Admin-Key: mba_YOUR_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"production"}'

# 3) پلن پولی را فعال کن
curl -X POST http://localhost:8000/v1/admin/tenants/TENANT_ID/plan \
  -H "X-MemoryBridge-Admin-Key: mba_YOUR_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"plan_code":"starter"}'
```

کلید `mbs_...` را فقط یک‌بار به مشتری بده (چت امن / ایمیل رمزدار).

---

## مرحله 3 — اگر مشتری بخواهد از اینترنت ببیند (هنوز رایگان‌تر)

گزینه‌ها بدون اجاره سرور ماهانه:
1. **Cloudflare Tunnel** یا **ngrok** موقتی روی لپ‌تاپت  
   - خوب برای دمو  
   - برای پروداکشن ۲۴/۷ ضعیف است (لپ‌تاپ خاموش = سرویس قطع)
2. وقتی اولین پول آمد → همان موقع سرور £5–10 بخر

قانون طلایی: قبل از اولین درآمد، سرور نخر.

---

## مرحله 4 — روال ماهانه فروش (بدون درگاه)

برای هر مشتری:
1. توافق روی Starter یا Growth
2. فاکتور بفرست
3. پول را چک کن
4. `.../plan` را روی starter/growth بگذار
5. اگر نپرداخت / قطع کرد → suspend:

```bash
curl -X POST http://localhost:8000/v1/admin/tenants/TENANT_ID/suspend \
  -H "X-MemoryBridge-Admin-Key: mba_YOUR_ADMIN_KEY"
```

---

## چه چیزی را فعلاً انجام نده

- Stripe Live
- دامنه پولی (مگر دمو لازم شد)
- سرور ماهانه
- وکیل / شرکت Ltd

این‌ها بعد از اولین پول واقعی.

---

## چک‌لیست ۷ روزه

روز ۱: ریپو بالا روی لپ‌تاپ  
روز ۲: یک دمو کامل خودت (signup + store + recall)  
روز ۳: پیام کوتاه فروش بنویس (۱ پاراگراف)  
روز ۴–۶: به ۱۰ سازنده AI / فروم / دوست فنی پیام بده  
روز ۷: اگر کسی خواست، Free بده؛ اگر پول داد، Starter دستی باز کن  

---

## پیام فروش آماده (کپی کن)

> MemoryBridge is a self-hosted encrypted memory API for AI apps.
> You get tenant isolation, revocable keys, and monthly quotas.
> Free to try. Starter £49/mo. I can set you up today and send the API key after payment.

---

وقتی اولین مشتری پول داد، برو سراغ `GO_LIVE.md` برای دامنه/سرور/Stripe.
