# f_local_config.json usage and option list

This file explains how to configure and run process f using local JSON config.

## Config file path
- Default config file: f_DBD_Company_List_Scraper_WIth_Filter/f_local_config.json
- Optional custom path:
  - python f_DBD_Company_List_Scraper_WIth_Filter/f_main.py --config f_DBD_Company_List_Scraper_WIth_Filter/f_local_config.json

## Reverse-engineered filter endpoint (UI + API hybrid)
- Endpoint: POST /api/v1/company-profiles/infos
- Base body keys:
  - keyword
  - type
  - sortBy
  - currentPage
- Filter keys added by UI:
  - pvCodeList
  - jpStatusList
  - jpTypeList
  - businessSizeList
  - capAmtMin, capAmtMax
  - totalIncomeMin, totalIncomeMax
  - netProfitMin, netProfitMax
  - totalAssetMin, totalAssetMax

Note:
- Runtime supports UI-first filter apply, then API replay for pagination.
- For config, put labels from lists below. The script applies them through UI and captures effective payload.
- If active filters exist but captured replay body lacks filter keys, runtime rebuilds a filtered replay body from config mapping.

## Config schema
- search_term: string (preferred search keyword key; default บริษัท)
- query: string
- sort_label: string (optional UI sort label; ex. จังหวัด (ก-ฮ))
- prefer_direct_search_url: boolean (default true)
- pages: integer (>0 or -1 for fetch-all)
- fetch_all_max_pages: integer >= 1 (hard safety cap when pages = -1)
- headless: boolean
- channel: chromium | chrome | msedge
- settle_seconds: integer >= 0
- cdp_url: string
- results_timeout_seconds: integer >= 10
- resume_from_page: integer >= 1 (continue replay from this page after init/filter/sort)
- track_progress_in_config: boolean (persist latest extracted page back into config)
- runtime_progress:
  - last_page_extracted: integer
  - updated_at: ISO datetime string
- storage_state: string path
- use_storage_state: boolean
- filters:
  - province_codes: string[]
  - status_codes: string[]
  - juristic_type_codes: string[]
  - business_size_codes: string[]
  - capital_min/capital_max: integer or null
  - revenue_min/revenue_max: integer or null
  - net_profit_min/net_profit_max: integer or null
  - assets_min/assets_max: integer or null

## Example config
```json
{
  "search_term": "บริษัท",
  "query": "บริษัท",
  "sort_label": "จังหวัด (ก-ฮ)",
  "prefer_direct_search_url": true,
  "pages": 5,
  "fetch_all_max_pages": 50,
  "headless": false,
  "channel": "chrome",
  "settle_seconds": 8,
  "cdp_url": "",
  "results_timeout_seconds": 180,
  "resume_from_page": 1,
  "track_progress_in_config": true,
  "runtime_progress": {
    "last_page_extracted": 0,
    "updated_at": ""
  },
  "storage_state": "storage_state.json",
  "use_storage_state": true,
  "filters": {
    "province_codes": [],
    "status_codes": ["ยังดำเนินกิจการอยู่"],
    "juristic_type_codes": ["บริษัทมหาชนจำกัด", "บริษัทจำกัด"],
    "business_size_codes": [],
    "capital_min": 5000000,
    "capital_max": 100000000,
    "revenue_min": 100000000,
    "revenue_max": null,
    "net_profit_min": 10000000,
    "net_profit_max": null,
    "assets_min": null,
    "assets_max": null
  }
}
```

## Runtime diagnostics outputs
- `last_run.log`: full timestamped execution log.
- `last_page_on.png`: latest page/UI wait screenshot for troubleshooting stale loading states.
- `f_search_result.json.debug.timing`: per-page + overall timing summary.

## Output lineage column (2026-04-06)
- New output field: `data_from_page`
- New output field: `data_retreive_at`
- New output field: `data_retrieve_approch`
- Purpose: track which result page each row came from.
- Population rules:
  - UI rows: `data_from_page = current UI page`
  - UI rows: `data_retreive_at = capture timestamp (ISO datetime)`
  - UI rows: `data_retrieve_approch = navigate_ui`
  - API replay rows: `data_from_page = replay currentPage`
  - API replay rows: `data_retreive_at = replay capture timestamp (ISO datetime)`
  - API replay rows: `data_retrieve_approch = api_replay`
  - Replay probe rows: `data_from_page = probe page` (typically page 1)
  - Replay probe rows: `data_retrieve_approch = api_replay`
- CSV impact:
  - `result_packed.csv` now includes `data_from_page`, `data_retreive_at`, and `data_retrieve_approch` as packed columns.

## UI page-nav behavior (2026-04-06 validation)
- Primary navigation path uses paginator input + Enter to move to target page.
- Runtime no longer auto-clicks adjacent pager arrows after input Enter in UI probe/recommit paths.
- Reason: when both `previous` and `next` controls are visible, heuristic arrow picks can hit `previous` and roll back page state.
- Validation run (no-filter, target page 3) confirmed:
  - page 1 rows loaded,
  - input jump reached page 3,
  - page 3 rows extracted (`target_rows=10`, `target_success=true`).

## Resume / Progress checkpoint behavior
- Runtime still performs normal initialization first:
  - open URL, apply filters/sort, capture infos contract.
- Replay continuation is controlled by `resume_from_page`:
  - `1`: normal behavior.
  - `>=2`: continue replay from that page.
- When `track_progress_in_config=true`, runtime updates config while running:
  - `runtime_progress.last_page_extracted`
  - `runtime_progress.updated_at`
  - mirror field `last_page_extracted` (top-level convenience value).

## Sort options
Source artifact: f_DBD_Company_List_Scraper_WIth_Filter/dumps/f_sort_options_labels.json

- `ชื่อนิติบุคคล (ก-ฮ)`
- `ประเภทนิติบุคคล (ก-ฮ)`
- `ประเภทธุรกิจ (ก-ฮ)`
- `จังหวัด (ก-ฮ)`
- `ทุนจดทะเบียน (มาก-น้อย)`
- `รายได้ (มาก-น้อย)`
- `กำไรสุทธิ (มาก-น้อย)`

## Sort behavior note (province sort)
- When `sort_label` is `จังหวัด (ก-ฮ)`, UI intent maps to API `sortBy=pvDesc`.
- Probing showed `pvDesc` can repeat the same companies across pages (pagination instability).
- Runtime therefore keeps a stability workaround during replay:
  - requested: `pvDesc`
  - actual replay sort: `jpName`
  - final output: post-sorted by province

You may see this in logs:
- `Replay payload sortBy: requested=pvDesc, actual_api=jpName (pvDesc pagination workaround)`

Probing findings (for awareness):
- `pvDesc`: unstable pagination (duplicate-heavy)
- `locationProvince.pvDesc`: stable in probe
- `pvCode`: stable in probe
- `jpName`: stable in probe

## Suggested search terms
- บริษัท
- ห้างหุ้นส่วน

## Option lists (harvested from live combobox)
Source artifact: f_DBD_Company_List_Scraper_WIth_Filter/dumps/f_filter_options_labels.json

### จังหวัดที่ตั้ง (77)
- กระบี่
- กรุงเทพมหานคร
- กาญจนบุรี
- กาฬสินธุ์
- กำแพงเพชร
- ขอนแก่น
- จันทบุรี
- ฉะเชิงเทรา
- ชลบุรี
- ชัยนาท
- ชัยภูมิ
- ชุมพร
- ตรัง
- ตราด
- ตาก
- นครนายก
- นครปฐม
- นครพนม
- นครราชสีมา
- นครศรีธรรมราช
- นครสวรรค์
- นนทบุรี
- นราธิวาส
- น่าน
- บึงกาฬ
- บุรีรัมย์
- ปทุมธานี
- ประจวบคีรีขันธ์
- ปราจีนบุรี
- ปัตตานี
- พระนครศรีอยุธยา
- พะเยา
- พังงา
- พัทลุง
- พิจิตร
- พิษณุโลก
- ภูเก็ต
- มหาสารคาม
- มุกดาหาร
- ยะลา
- ยโสธร
- ระนอง
- ระยอง
- ราชบุรี
- ร้อยเอ็ด
- ลพบุรี
- ลำปาง
- ลำพูน
- ศรีสะเกษ
- สกลนคร
- สงขลา
- สตูล
- สมุทรปราการ
- สมุทรสงคราม
- สมุทรสาคร
- สระบุรี
- สระแก้ว
- สิงห์บุรี
- สุพรรณบุรี
- สุราษฎร์ธานี
- สุรินทร์
- สุโขทัย
- หนองคาย
- หนองบัวลำภู
- อำนาจเจริญ
- อุดรธานี
- อุตรดิตถ์
- อุทัยธานี
- อุบลราชธานี
- อ่างทอง
- เชียงราย
- เชียงใหม่
- เพชรบุรี
- เพชรบูรณ์
- เลย
- แพร่
- แม่ฮ่องสอน

### สถานะ (11)
- ยังดำเนินกิจการอยู่
- ฟื้นฟู
- คืนสู่ทะเบียน
- เลิก
- พิทักษ์ทรัพย์เด็ดขาด
- ล้มละลาย
- เสร็จการชำระบัญชี
- ร้าง
- ควบ
- แปรสภาพ
- สิ้นสภาพ

### ประเภทนิติบุคคล (8)
- บริษัทมหาชนจำกัด
- บริษัทจำกัด
- ห้างหุ้นส่วนจำกัด
- ห้างหุ้นส่วนสามัญนิติบุคคล
- นิติบุคคลต่างด้าว
- กิจการร่วมค้า
- สมาคมการค้า
- หอการค้า

### ขนาดธุรกิจ (3)
- ธุรกิจขนาดเล็ก (S)
- ธุรกิจขนาดกลาง (M)
- ธุรกิจขนาดใหญ่ (L)
