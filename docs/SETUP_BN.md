# Eilblick — সেটআপ গাইড (বাংলা)

এই রিপোতে পুরো জার্মান নিউজ শর্টস সিস্টেম তৈরি আছে। আপনাকে শুধু ৭টা API key / secret GitHub-এ বসাতে হবে।
কোনো কোড এডিট করতে হবে না।

---

## সিস্টেম কীভাবে কাজ করে (প্রতিটা স্লটে)

```
GitHub Actions (নির্দিষ্ট সময়ে নিজে চালু হয়)
  │
  ├─ ১. ২১টা বিশ্বস্ত জার্মান/অস্ট্রিয়ান/সুইস নিউজ সোর্সের RSS পড়ে
  │     (tagesschau, ZDFheute, DW, Deutschlandfunk, SPIEGEL, ZEIT, FAZ, SZ, Handelsblatt,
  │      WiWo, heise, ORF, DER STANDARD, SRF, NZZ, n-tv, WELT, Golem + Google News + Google Trends DE)
  ├─ ২. একই খবর কয়টা মিডিয়া দিয়েছে সেটা গুনে "হট" খবর বের করে
  │     → শুধু ≥২টা মিডিয়ায় আসা খবর নেয় (গুজব বাদ)
  │     → রক্ত/সহিংসতা/গসিপ/লোকাল দুর্ঘটনা বাদ (মনিটাইজেশন সেফ)
  ├─ ৩. AI নিউজ ডেস্ক (Claude) ৪টা খবর বাছে — কমপক্ষে ৩টা DACH/ইউরোপের,
  │     Tagesschau স্টাইলে জার্মান স্ক্রিপ্ট + টাইটেল/ডেসক্রিপশন/ট্যাগ/ফেসবুক ক্যাপশন লেখে
  ├─ ৪. প্রতিটা খবরের আসল আর্টিকেল পেজ থেকে ওই খবরের ছবি (২–৪টা, ভিন্ন ভিন্ন মিডিয়া থেকে)
  │     নামিয়ে `tmp_media/` টেম্পোরারি ফোল্ডারে রাখে
  ├─ ৫. ElevenLabs (voice DEZHhPbmb8LVZmWufkCh) দিয়ে নিউজ-স্টাইল জার্মান ভয়েস
  ├─ ৬. নিউজ চ্যানেলের মতো গ্রাফিক্স বানায়: লোগো, AKTUELL + সময়, ছবি কার্ড (প্রতি ~৩ সেকেন্ডে ছবি বদলায়),
  │     লাল কিকার (BERLIN/WIEN…), বড় হেডলাইন, ভয়েসের সাথে মিলিয়ে ক্যাপশন, "Quelle:", স্ক্রলিং টিকার,
  │     আপনার signature sound ব্যাকগ্রাউন্ডে (ভয়েসের সময় নিজে থেকে ভলিউম কমে যায়), শেষে লোগো এনিমেশন
  ├─ ৭. YouTube + Facebook-এ আপলোড (স্লটের সঠিক সময়ে পাবলিশ হওয়ার জন্য শিডিউল করে)
  └─ ৮. টেম্পোরারি ছবির ফোল্ডার ডিলিট → পরের ভিডিওর জন্য একদম খালি
```

**সময়সূচি (জার্মান সময়):** 07:30 · 12:30 · 17:30 · 20:45
**বাংলাদেশ সময় (শীতকাল, নভেম্বর–মার্চ):** 12:30 PM · 5:30 PM · 10:30 PM · 1:45 AM
প্রতিটা ভিডিও ৪০–৫০ সেকেন্ড, কখনো ৫০ সেকেন্ডের বেশি না (বেশি হলে সিস্টেম নিজেই ছোট করে)।
৪র্থ স্লটে সাবস্ক্রাইবার নোটিফিকেশন বন্ধ থাকে (YouTube-এর দিনে ৩ নোটিফিকেশন লিমিট)।

---

## ধাপ ০ — রিপো Private করুন (জরুরি)

রিপোটা এখন **Public**। Public রিপোর ভিডিও-আর্টিফ্যাক্ট আর পাবলিশ লগ যে কেউ দেখতে পারে।
API key গুলো Secrets-এ থাকায় সেগুলো সেফ, কিন্তু তারপরও Private রাখা ভালো।
`Settings → General → (নিচে) Danger Zone → Change visibility → Private`
(Private-এ GitHub Actions মাসে ২০০০ মিনিট ফ্রি, এই সিস্টেম মাসে আনুমানিক ৯০০–১২০০ মিনিট লাগবে।)

---

## ধাপ ১ — ElevenLabs API key

1. elevenlabs.io → Profile → **API Keys** → Create key
2. Permission: Text to Speech ✅, Voices (read) ✅
3. কপি করে রাখুন → GitHub secret নাম: `ELEVENLABS_API_KEY`

## ধাপ ২ — Anthropic (Claude) API key — নিউজ ডেস্কের জন্য

খবর বাছাই আর জার্মান স্ক্রিপ্ট লেখার জন্য।
1. console.anthropic.com → **API Keys** → Create Key
2. Billing-এ কিছু ক্রেডিট দিন (প্রতি ভিডিওতে কয়েক সেন্ট খরচ)
3. GitHub secret নাম: `ANTHROPIC_API_KEY`

## ধাপ ৩ — YouTube API (Eilblick চ্যানেলের জন্য নতুন প্রজেক্ট)

> অন্য চ্যানেলের (Exportain / Breach Uncovered) প্রজেক্টের সাথে মেশাবেন না — Eilblick-এর জন্য আলাদা প্রজেক্ট বানান।

**৩.১ Google Cloud প্রজেক্ট**
1. console.cloud.google.com → উপরে প্রজেক্ট সিলেক্টর → **New Project** → নাম `eilblick`
2. `APIs & Services → Library` → **YouTube Data API v3** → Enable

**৩.২ OAuth consent screen**
1. `APIs & Services → OAuth consent screen` (Google Auth Platform) → User type **External**
2. App name `Eilblick Uploader`, support email আপনার ইমেইল
3. **Audience → Publish app → In production** করুন
   ⚠️ "Testing" মোডে রাখলে refresh token ৭ দিন পর মেয়াদ শেষ হয়ে যায় — তখন আপলোড বন্ধ হবে।

**৩.৩ OAuth Client**
1. `Credentials → Create credentials → OAuth client ID` → Type: **Web application**
2. Authorized redirect URIs-এ যোগ করুন: `https://developers.google.com/oauthplayground`
3. Create → **Client ID** আর **Client secret** কপি করুন
   → secret নাম: `YT_CLIENT_ID`, `YT_CLIENT_SECRET`

**৩.৪ Refresh token (OAuth Playground দিয়ে, কোনো কোড লাগবে না)**
1. developers.google.com/oauthplayground খুলুন
2. ডান দিকে ⚙️ → ✅ **Use your own OAuth credentials** → উপরের Client ID / Secret বসান
3. বাম দিকে "Input your own scopes" বক্সে এই তিনটা লিখুন (স্পেস দিয়ে):
   ```
   https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.force-ssl https://www.googleapis.com/auth/youtube.readonly
   ```
4. **Authorize APIs** → গুগল অ্যাকাউন্ট সিলেক্ট → **চ্যানেল সিলেক্ট স্ক্রিনে Eilblick চ্যানেলটা বাছুন** (এটা খুব জরুরি)
   → "Google hasn't verified this app" এলে Advanced → Go to Eilblick Uploader → Allow
5. **Exchange authorization code for tokens** → **Refresh token** কপি → secret নাম: `YT_REFRESH_TOKEN`

**৩.৫ API Audit (পাবলিক ভিডিওর জন্য বাধ্যতামূলক)**
নতুন, অডিট-ছাড়া API প্রজেক্ট থেকে আপলোড করা ভিডিও YouTube **Private-এ লক** করে দেয়।
তাই "YouTube API Services – Audit and Quota Extension Form" পূরণ করুন (প্রজেক্ট নম্বর, চ্যানেল URL,
ব্যবহার: "automated upload of our own news Shorts to our own channel")। অনুমোদন সাধারণত কয়েক দিন–সপ্তাহ লাগে।
অনুমোদন না আসা পর্যন্ত চাইলে `--no-upload` দিয়ে শুধু ভিডিও বানিয়ে রাখা যায়।
কোটা: দিনে ৪ আপলোড × ১৬০০ ইউনিট = ৬৪০০ — ডিফল্ট ১০,০০০ ইউনিটেই চলবে।

## ধাপ ৪ — Facebook Page (Reels) — System User টোকেন (কখনো মেয়াদ শেষ হয় না)

আপনার Business Manager verified, তাই সবচেয়ে মজবুত উপায় System User:

1. developers.facebook.com → **My Apps → Create App** → Use case: *Other* → Type: **Business**
   → নাম `Eilblick Publisher` → আপনার Business Portfolio সিলেক্ট (অন্য প্রজেক্টের অ্যাপ ব্যবহার করবেন না)
2. business.facebook.com → **Settings → Accounts → Pages** → Eilblick পেজ যে আপনার বিজনেসে আছে নিশ্চিত করুন
3. **Settings → Users → System users → Add** → নাম `eilblick-bot`, role **Admin**
4. ওই system user → **Assign assets**:
   - Pages → Eilblick → **Full control** (বা অন্তত Content + Community activity)
   - Apps → Eilblick Publisher → **Full control**
5. **Generate new token** → App: Eilblick Publisher → Expiration: **Never** → Permissions:
   `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `pages_manage_engagement`, `publish_video`, `business_management`
6. যে টোকেন আসবে সেটা দিয়ে Graph API Explorer-এ রান করুন: `GET /me/accounts`
   → Eilblick পেজের `access_token` আর `id` কপি করুন
   → secret নাম: `FB_PAGE_TOKEN` (পেজের access_token) আর `FB_PAGE_ID` (পেজের id)
7. অ্যাপটা **Live** মোডে দিন (App Dashboard → Publish)। নিজের পেজে নিজের system user দিয়ে পোস্ট করতে
   App Review সাধারণত লাগে না।

## ধাপ ৫ — GitHub-এ Secrets বসানো

রিপো → **Settings → Secrets and variables → Actions → New repository secret** — এই ৭টা:

| Secret নাম | কোথা থেকে |
|---|---|
| `ANTHROPIC_API_KEY` | ধাপ ২ |
| `ELEVENLABS_API_KEY` | ধাপ ১ |
| `YT_CLIENT_ID` | ধাপ ৩.৩ |
| `YT_CLIENT_SECRET` | ধাপ ৩.৩ |
| `YT_REFRESH_TOKEN` | ধাপ ৩.৪ |
| `FB_PAGE_ID` | ধাপ ৪.৬ |
| `FB_PAGE_TOKEN` | ধাপ ৪.৬ |

## ধাপ ৬ — চেক ও টেস্ট

1. রিপো → **Actions** ট্যাব → (প্রথমবার হলে "I understand… enable workflows" চাপুন)
2. **Check setup (keys + news feeds)** → Run workflow → সব ✓ কিনা দেখুন, আর আজকের হট খবরের লিস্ট দেখুন
3. **Eilblick News Shorts** → Run workflow → slot: `mittag`, **Upload: ❌ (টিক তুলে দিন)** → Run
   → শেষ হলে রানের পেজে নিচে **Artifacts** থেকে ভিডিও ডাউনলোড করে দেখুন
4. পছন্দ হলে আর কিছু করতে হবে না — শিডিউল অনুযায়ী প্রতিদিন ৪টা নিজে থেকে বানিয়ে আপলোড হবে।

---

## যা হাতে করতে হবে (API-এর সীমাবদ্ধতা)

- **কমেন্ট পিন করা:** সিস্টেম ভিডিও পাবলিশের পরে প্রথম কমেন্টে জার্মান প্রশ্ন পোস্ট করে,
  কিন্তু YouTube API দিয়ে কমেন্ট **পিন** করা যায় না — চাইলে স্টুডিও অ্যাপ থেকে হাতে পিন করবেন।
- **চ্যানেল সেটিংস (একবার):** YouTube Studio → Settings → Channel → Country: Germany,
  Default upload: Language German, Category News & Politics।

## সতর্কতা — ছবির কপিরাইট

আপনার নির্দেশ অনুযায়ী সিস্টেম নিউজ আর্টিকেলের আসল ছবিই নেয়, প্রতিটা ছবিতে ক্রেডিট ("Bild: tagesschau.de")
আর নিচে "Quelle:" দেখায়। তবে খেয়াল রাখবেন: dpa/Reuters/AP-এর ছবি কপিরাইটেড — শুধু ক্রেডিট দিলেই
আইনগত অনুমতি হয় না, তাই মাঝে মাঝে copyright claim বা আপত্তি আসতে পারে (বিশেষ করে মনিটাইজেশন রিভিউর সময়)।
ঝুঁকি কমাতে যা করা আছে: ছবি ফুল-স্ক্রিন না দেখিয়ে ফ্রেমের ভেতর কার্ডে, সাথে নিজস্ব গ্রাফিক্স, আর
ছবি কম পেলে Wikimedia Commons-এর ফ্রি-লাইসেন্স ছবি নেয়। কোনো claim এলে আমাকে জানাবেন — তখন
লাইসেন্স-ফ্রি সোর্সকে প্রথমে রাখার নিয়ম চালু করে দেব।

## ফাইল ম্যাপ

| ফাইল | কাজ |
|---|---|
| `config/settings.yaml` | স্লট/সময়, ভয়েস, ভিডিও রঙ, অডিও লেভেল, SEO বেস ট্যাগ |
| `config/sources.yaml` | নিউজ সোর্স লিস্ট + ব্লক করা টপিক |
| `assets/logo_mark.png` | ব্যাকগ্রাউন্ড-ছাড়া লোগো (প্রতি ভিডিওতে উপরে + শেষে) |
| `assets/audio/signature_bed.mp3` | চ্যানেলের signature sound (ব্যাকগ্রাউন্ড) |
| `eilblick/feeds.py` | খবর সংগ্রহ + হট খবর র‍্যাঙ্কিং |
| `eilblick/editor.py` | AI নিউজ ডেস্ক (জার্মান স্ক্রিপ্ট + SEO) |
| `eilblick/images.py` | খবরের ছবি → টেম্পোরারি ফোল্ডার → ডিলিট |
| `eilblick/render.py` | নিউজ চ্যানেল গ্রাফিক্স |
| `eilblick/audio.py` | সাউন্ড মিক্স (ducking, whoosh, beep, stinger) |
| `state/published.json` | কোন স্লট কবে পাবলিশ হলো (ডুপ্লিকেট আটকায়) |
