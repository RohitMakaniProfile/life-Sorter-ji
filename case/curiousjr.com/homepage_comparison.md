# 🔍 CuriousJr Homepage — Comparison Report

> Generated: 2026-04-14 16:54 UTC

Comparing **two independent scrapes** of `curiousjr.com` homepage:

| | Source A | Source B |
|---|---|---|
| **Source** | Case file (`format1_crawl_data.json`) | DB (`scraped_pages` ID=52) |
| **Method** | Static HTTP (httpx + regex) | JS-rendered (Headless Chrome / Playwright) |
| **Crawled at** | 2026-03-25 11:50 UTC | 2026-04-14 16:31 UTC |
| **URL used** | `https://www.curiousjr.com/` | `https://curiousjr.com` |

---

## 1️⃣ Meta & Title

| Field | Source A | Source B |
|---|---|---|
| **Title** | CuriousJr | Online Tuition Classes for 1st to 10th Kids | CuriousJr | Online Tuition Classes for 1st to 10th Kids |
| **Meta Description** | Live online tuition for kids! Expert-led classes in Math, Science, English & more. Fun, interactive learning for classes 1st-10th. Start today! | ❌ Empty |
| **H1** | Learning made fun for Curious Minds! | Learning made fun for Curious Minds!, Learning At Your Pace Anytime, Anywhere |

> ⚠️ **Key difference**: Source B (`meta_description`) is **empty** even though the site has one.
> The JS-rendered scraper is not extracting the `<meta name="description">` tag correctly.

---

## 2️⃣ SEO Basics

| Check | Source A | Source B |
|---|---|---|
| Meta tags present | ✅ Yes | ❌ No (empty) |
| Mobile viewport | ✅ Yes | Not captured |
| Sitemap detected | ❌ No | Not captured |
| JSON-LD Schema | None | None |
| JS-rendered | ❌ No | ✅ Yes |

---

## 3️⃣ Tech Stack

| # | Source A (HTML pattern matching) | Source B (Network request analysis) |
|---|---|---|
| 1 | React/Next.js | Google Analytics (G-YLS8T7FSRC) |
| 2 | Google Analytics | Firebase (auth + remote config) |
| 3 | Google Tag Manager | Sentry (error tracking) |
| 4 | — | Microsoft Clarity (session recording) |
| 5 | — | PenPencil API / Next.js |
| 6 | — | Unleash (feature flags) |

> 📝 **Source B reveals hidden runtime infrastructure** not visible in static HTML:
> Firebase (auth/config), Sentry (error monitoring), Microsoft Clarity (session heatmaps),
> Unleash (feature flag system), PenPencil API (PW's internal backend).

---

## 4️⃣ CTAs

**Source A (6 found):** `View Learning Programs` | `Book a Demo` | `Get Started` | `Know More` | `Login or register` | `Download on Play Store`

**Source B (5 found, extracted from body text):** `View Learning Programs` | `Book a Demo` | `Get Started` | `Know More` | `Login/Register`

> ✅ Both sources confirm the **same CTAs** are present on the homepage.

---

## 5️⃣ Navigation / Internal Links

| | Count | Notes |
|---|---|---|
| Source A | 15 links | Deep class-level links from static HTML dropdowns |
| Source B | 5 links | Top-level links from rendered DOM only |

### Links in Source A but missing from Source B:
- `https://www.curiousjr.com/blogs`
- `https://www.curiousjr.com/contact-us`
- `https://www.curiousjr.com/in/mental-maths/class-1`
- `https://www.curiousjr.com/in/mental-maths/class-2`
- `https://www.curiousjr.com/in/mental-maths/class-3`
- `https://www.curiousjr.com/in/mental-maths/class-4`
- `https://www.curiousjr.com/in/mental-maths/class-5`
- `https://www.curiousjr.com/in/school-curriculum/class-3`
- `https://www.curiousjr.com/in/school-curriculum/class-4`
- `https://www.curiousjr.com/in/school-curriculum/class-5`
- `https://www.curiousjr.com/in/school-curriculum/class-6`
- `https://www.curiousjr.com/in/school-curriculum/class-7`
- `https://www.curiousjr.com/in/school-curriculum/class-8`
- `https://www.curiousjr.com/login`
- `https://www.pw.live/about-us`

### Links in Source B but missing from Source A:
- `https://curiousjr.com/blogs`
- `https://curiousjr.com/contact-us`
- `https://curiousjr.com/login`
- `https://curiousjr.com/policies/privacy`
- `https://curiousjr.com/policies/terms-and-conditions`

> ⚠️ **Insight**: Static crawl captured 15 links including all class-level `/in/school-curriculum/class-N`
> and `/in/mental-maths/class-N` paths (from dropdown HTML). JS-rendered scraper only surfaced
> top-level navigation links + policy pages.

---

## 6️⃣ Headings

| | Count |
|---|---|
| Source A | 20 headings |
| Source B | 27 (2 H1, 7 H2, 18 H3) |

### 🆕 Headings in Source B but NOT in Source A:
- `Learning made fun for Curious Minds!`
- `Learning At Your Pace Anytime, Anywhere`
- `Hand’s-On Learning and More!`
- `From Alakh Sir’s Desk`
- `Stories of our Brighest Stars!`
- `Alakh Pandey`
- `Improved my grades in school!`
- `I love all my mentors : They help me with all my doubts`
- `My Parents are happy. Thanks PW CJr!`
- `Vishal Sir`
- `Shivangi Ma'am`
- `Areebah Ma'am`
- `Chetna Ma'am`
- `Sonakshi Ma'am`
- `Deepak Sir`
- `Zufa Ma'am`
- `Trayee Ma'am`
- `Tubia Ma'am`
- `More About Us`
- `Country`

### ❌ Headings in Source A but NOT in Source B:
- `Let your child start learning how to excel in School Curriculum, Maths & English!`
- `Choose from our Best Courses for your kid`
- `Hand's-On Learning and More!`
- `Explore Our Latest Features`
- `Interactive Live Classes`
- `The Two-Teacher Model`
- `Tailored Practice Solutions`
- `Homework Assistance`
- `Daily Performance Tracking`
- `From Alakh Sir's Desk`
- `On a Mission to Revolutionise Traditional Education Practices`
- `Stories of our Brightest Stars!`
- `Students and Parents love Curious Jr`

### ⚠️ Typos found in live site (Source B):

| Element | Live value (Source B) | Correct spelling |
|---|---|---|
| Heading | `Stories of our Brighest Stars!` | `Brightest` |
| Heading | `On a Mission to Revolutionise Traditional Education Pratices` | `Practices` |

---

## 7️⃣ Country / Geo Targeting

> Source B captured a **country selector modal** rendered by JavaScript:

- **India**
- **UAE**

> ❌ Source A (static crawl) missed this completely — the modal is JS-injected.

---

## 8️⃣ Images

| | |
|---|---|
| Source A | ❌ No image URLs captured |
| Source B | ✅ **74 image URLs** catalogued |

**CDN used:** `static.pw.live` (Physics Wallah CDN) + `d2x5rmu49hse8s.cloudfront.net`

> All media is served from the **PW CDN** — confirms CuriousJr shares PW's infrastructure.

---

## 9️⃣ AI-Summarised Markdown (DB)

> The DB stores an LLM-generated summary alongside the raw data:

```markdown
CuriousJr, an online tuition platform associated with Physicswallah (founded by Alakh Pandey), offers classes for students in grades 1 through 10. The platform focuses on interactive, practice-led learning with features including live classes, a two-teacher model (educator plus personal mentor), 24/7 support, daily progress tracking, and homework assistance.

**Key Programs:**
*   **After-School:** For grades 1-9; covers English, Maths, Science, and Social Studies aligned with CBSE, ICSE, and State Boards.
*   **Learn English:** For grades 1-8; offers Cambridge certification (CEFR aligned) with small class sizes (4-5 learners).
*   **Maths Learning:** For grades 1-8; focuses on mental math and calculation speed with 10-15 learners per class.

**Methodology & Faculty:**
The teaching approach emphasizes hands-on projects, real-life applications, and play-based learning to build communication and leadership skills. The qualified faculty holds degrees like B.Sc, M.Sc, and B.Ed with CTET/HTET qualifications.

**Additional Info:**
The platform provides a mobile app for flexible learning. Student testimonials cite improved grades and mentor support. Services are available in India, UAE, Saudi Arabia, Kuwait, and Qatar.
```

---

## 🔟 Side-by-Side Summary

| Dimension | Source A (Static, Mar 2026) | Source B (JS-rendered, Apr 2026) |
|---|---|---|
| Scrape method | httpx + regex | Playwright headless Chrome |
| Meta description | ✅ Captured correctly | ❌ Empty (bug) |
| Nav links | 15 (deep class paths) | 5 (top-level only) |
| Tech detection depth | Surface (HTML patterns) | Deep (network requests) |
| Firebase / Sentry / Clarity | ❌ Not detected | ✅ Detected |
| Feature flags (Unleash) | ❌ Not detected | ✅ Detected |
| Country geo-selector | ❌ Not captured | ✅ In body text |
| Image URLs | ❌ Not captured | ✅ 63 images |
| Typos | N/A | 2 typos detected |
| H1 / Core CTAs / Programs | ✅ Identical | ✅ Identical |
| AI summary | ❌ None | ✅ In `markdown` column |

---

## 💡 Action Items

### For the scraper (Source B fix):
1. **Fix meta description extraction** — `meta_description` is empty; add explicit `document.querySelector('meta[name="description"]')?.content` extraction.
2. **Improve link capture** — extract links from JS-rendered dropdown menus, not just visible hrefs.

### For the CuriousJr website:
3. **Fix typos**: `Brighest → Brightest`, `Pratices → Practices`.
4. **Add JSON-LD schema markup** — both scrapes confirm zero structured data. Add `Course`, `Organization`, `FAQPage` schemas for SEO.
5. **Add social media links** — homepage has no direct social links to CuriousJr's own accounts.
6. **Generate sitemap.xml** — neither source detected a sitemap.
