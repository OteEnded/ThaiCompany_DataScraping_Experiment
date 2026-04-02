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

## Config schema
- search_term: string (preferred search keyword key; default บริษัท)
- query: string
- pages: integer (>0 or -1 for fetch-all)
- headless: boolean
- channel: chromium | chrome | msedge
- settle_seconds: integer >= 0
- cdp_url: string
- results_timeout_seconds: integer >= 10
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
  "pages": 5,
  "headless": false,
  "channel": "chrome",
  "settle_seconds": 8,
  "cdp_url": "",
  "results_timeout_seconds": 180,
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
