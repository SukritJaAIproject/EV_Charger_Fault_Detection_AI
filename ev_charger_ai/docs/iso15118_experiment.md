# การทดลอง: แนบมาตรฐาน ISO 15118-2:2014 เข้าไปในระบบตรวจจับปัญหา

**คำถาม** — ถ้า AI ได้อ่านมาตรฐานจริง แทนที่จะเรียนรู้ threshold เอาจากข้อมูลของ
ตู้ชาร์จฟลีตนี้ ผลลัพธ์จะต่างไหม และต่างตรงไหน

**วิธีตอบ** — เทรน 3 ระบบบนข้อมูลชุดเดียวกัน ground truth ชุดเดียวกัน และ
train/test split เดียวกัน ต่างกันแค่ว่า "รู้จักมาตรฐานแค่ไหน"

| arm | features | rules | weights |
|---|---|---|---|
| `baseline` | 33 (เดิม) | rule engine ที่ปรับ threshold จากข้อมูลฟลีตนี้ | เทรนใหม่บน label ที่แก้แล้ว |
| `iso_rules` | 33 (เดิม) | + ISO rule layer (อ้าง requirement id ทุกข้อ) | **ใช้ weights ของ baseline ทั้งชุด** |
| `iso` | 33 + 27 ISO | + ISO rule layer | เทรนใหม่ทั้งหมดบน 60 features |

`baseline -> iso_rules` วัดว่า *กฎ* จากมาตรฐานมีค่าแค่ไหน (ไม่มีอะไรเปลี่ยนนอกจาก
rule layer มองเห็น `fs.iso`) ส่วน `iso_rules -> iso` วัดว่า *ฟีเจอร์* จากมาตรฐาน
เพิ่มอะไรอีก เมื่อโมเดลที่เรียนรู้ได้เห็นมันด้วย

    ./run_arm.sh baseline  train_traditional train_nn train_rl benchmark
    ./run_arm.sh iso_rules benchmark              # ใช้ artifacts ของ baseline
    ./run_arm.sh iso       dataset train_traditional train_nn train_rl benchmark
    python benchmark/compare_arms.py test
    python benchmark/attribute_alerts.py test     # กฎไหนเป็นคนพูดก่อน
    python benchmark/iso_label_audit.py           # ถ้า label เขียนตามมาตรฐานล้วน

## ข้อมูลจริงคือ DIN 70121 — ทำไมถึงใช้ ISO 15118-2 ได้

pcap ของฟลีตนี้พูด `urn:din:70121:2012:MsgDef` ซึ่งเป็นรุ่นก่อนของ ISO 15118-2
แต่ในบรรดา `supportedAppProtocolReq` ที่จับได้ **82 จาก 435 ครั้งเสนอ
`urn:iso:15118:2:2013:MsgDef` มาด้วย** คือรถประมาณ 19% รองรับ ISO 15118-2 อยู่แล้ว
และที่สำคัญกว่านั้น: ชุดข้อความ DC, state machine และโมเดลเวลาเป็นรูปแบบเดียวกัน
ต่างกันที่ชื่อ 3 ข้อความ (ดู `ISO_NAME` ใน `core/iso15118.py`)

ISO 15118-2 คือฉบับที่ **ตีพิมพ์ตัวเลขจริง** ว่าแต่ละ request รอคำตอบได้กี่วินาที,
sequence ค้างได้กี่วินาที, CableCheck/PreCharge นานได้แค่ไหน และ request ไหน
ต่อจาก response ไหนได้บ้าง — ทำให้ threshold ทุกตัวอ้างเลขข้อในมาตรฐานได้
แทนที่จะเป็นเลขที่จูนมาจากข้อมูล

## สิ่งที่ดึงมาจากมาตรฐาน

`core/iso15118.py` ถอดมาตรง ๆ จาก PDF:

- **Table 109** — `V2G_EVCC_Msg_Timeout` รายข้อความ (CurrentDemandReq = 0.25 s,
  PowerDeliveryReq = 5 s, ที่เหลือ 2 s) และ `V2G_SECC_Msg_Performance_Time`
  (CurrentDemandRes = 0.025 s, PowerDeliveryRes = 4.5 s, ที่เหลือ 1.5 s)
- **Table 109** — `V2G_EVCC_Sequence_Performance_Time` 40 s,
  `V2G_SECC_Sequence_Timeout` 60 s, `V2G_EVCC_Ongoing_Timeout` 60 s,
  `V2G_SECC_Ongoing_Performance_Time` 55 s
- **Table 111** — CommunicationSetup 18/20 s, CableCheck 38/40 s, PreCharge 5/7 s
- **Figure 102 / clause 8.8.4.2.3 + 8.8.4.3.3** — ตาราง "allowed next request"
  ของ DC state machine
- **clause 8.8.2/8.8.3** — ความหมายของ ResponseCode (`OK*` / `FAILED*`),
  [V2G2-459] `FAILED_SequenceError` เมื่อได้ request ที่ไม่คาดหมาย
- **[V2G2-880] / [V2G2-881]** — DC_EVSEStatusCode และ EVErrorCode ที่ไม่มี
  requirement ชัดเจน ถือเป็นข้อมูลเท่านั้น ห้ามให้มีผลต่อกระบวนการชาร์จ

ค่าคงที่ทั้ง 46 ตัวถูก cross-check กับการอ่าน PDF อีกรอบหนึ่งที่ทำแยกกัน
(7 agent อ่านคนละ clause แล้วมี verifier อ่านซ้ำเพื่อหาข้อผิด) — **ตรงกันทั้ง 46 ตัว
ไม่มีข้อขัดแย้ง**

## ฟีเจอร์ ISO 27 ตัว

`core/iso_features.py` คำนวณ online ไม่มี lookahead ทุกตัวเป็น *อัตราส่วนต่อ
ขีดจำกัดที่มาตรฐานกำหนด* ดังนั้นค่า 1.0 แปลว่า "ถึงเกณฑ์ที่มาตรฐานเองบอกว่าผิด"
เสมอ และแยก **Timeout** (มาตรฐานสั่งให้ตัด session) ออกจาก **Performance Time**
(แค่ช้ากว่าเกณฑ์ ไม่ใช่ error) ตาม clause 8.7.1 อย่างเคร่งครัด

ข้อดีที่ไม่ได้ตั้งใจ: LINK_STATUS poll ของ PLC เดินอยู่ ~20 Hz แม้ตอน V2G dialog
ค้าง ดังนั้น sequence timer จึงโตให้เห็น *ระหว่างที่ยังค้างอยู่* ไม่ใช่ตอนที่
dialog กลับมา

## กฎที่ทดลองแล้ว "ไม่ผ่าน" — และทำไมถึงสำคัญ

สองข้อนี้มาตรฐานเขียนไว้ชัด แต่ฟลีตนี้ละเมิดตอนที่ session ปกติดี จึงถูกลดชั้น
จาก hard rule เหลือแค่ feature:

1. **ลำดับปิด session** — clause 8.8.4.3.3 [V2G2-593] บอกว่าหลัง
   `CurrentDemandRes` ส่งได้แค่ `CurrentDemandReq` หรือ `PowerDeliveryReq`
   เท่านั้น ต้อง `PowerDelivery(Stop)` ก่อนถึงจะ `SessionStopReq` ได้
   วัดจริง: รถบนฟลีตนี้กระโดดจาก CurrentDemand ไป SessionStopReq ตรง ๆ
   ใน session ที่ชาร์จจบสวยงาม และตู้ตอบ OK แทนที่จะเป็น `FAILED_SequenceError`
   ตามที่ [V2G2-459] กำหนด
2. **PreCharge 7 วินาที** — [V2G2-704/706] วัดจริง: session ปกติใช้เวลา
   PreCharge เกิน 19 วินาที โดยแรงดันยังห่างเป้าอยู่มาก แล้วก็ชาร์จต่อได้ปกติ

บทเรียน: **ไม่เป็นไปตามมาตรฐาน ≠ เสีย** การเอามาตรฐานมาใช้ตรง ๆ โดยไม่วัดกับ
ข้อมูลจริงก่อน จะได้ระบบที่แจ้งเตือนผิดเยอะ

## ผลลัพธ์ (test 472 sessions: 222 faulty + 250 clean, seed เดียวกันทั้ง 3 arms)

| detector | score base → +rules → +feat | recall base → +feat | FAR base → +feat |
|---|---|---|---|
| TraditionalAI | 68.0 → 68.5 → **69.0** | 73.4% → 76.6% | 22.0% → 23.6% |
| AgenticAI | 68.2 → 67.6 → 68.5 | 81.1% → 81.1% | 25.2% → 26.8% |
| MultiAgent | 55.2 → **62.2** → 62.2 | 56.3% → **68.9%** | 20.8% → 21.2% |
| AIAgent | 53.8 → **58.6** → 57.5 | 62.2% → **71.6%** | 39.6% → 46.0% |
| RL (DQN) | 40.2 → 40.2 → **48.5** | 17.6% → **31.1%** | 3.6% → 5.2% |

**ข้อค้นพบหลัก: มาตรฐานสองครึ่งช่วยคนละสถาปัตยกรรม**

- *กฎ* (`baseline → iso_rules`) ช่วยตัวที่รวมหลักฐานเป็น: MultiAgent +7.1,
  AIAgent +4.8 — แต่ให้ RL **0.0 เป๊ะ** เพราะ RL ไม่มี rule layer ให้ใส่
- *ฟีเจอร์* (`iso_rules → iso`) ช่วยตัวที่เรียนรู้ล้วน: RL +8.2 score,
  **+13.5pp recall** (ขยับมากสุดในการทดลองนี้) — แต่ให้ MultiAgent **+0.0**
  เพราะมันได้ข้อมูลชุดเดียวกันไปแล้วผ่านกฎ

RL ที่ได้ `0.0` ทุกช่องใน arm กลาง คือ control ที่ยืนยันว่า harness ไม่รั่ว

**ขยับที่ไหน** — `SESSION_ABORT` (78 sessions) ล้วน ๆ: MultiAgent 29→65,
AIAgent 49→76, RL 13→32, TraditionalAI 69→78
`PROTOCOL_FAILED` / `EV_ERROR` เต็ม 100% อยู่แล้ว 4 ใน 5 ตัว — ไม่มีที่ให้ขยับ
`SLAC_FAILURE` **ไม่ขยับเลยสักตัว** เพราะ SLAC อยู่ใน ISO 15118-**3** ไม่ใช่ part 2

**กฎไหนเป็นคนพูด** (attribution, MultiAgent 52 จาก 153 on-time):
`[V2G2-711/713]` Ongoing 19, `Table 109` message timeout 14, `[V2G2-443]` 7,
`[V2G2-706]` 6, `Fig.102` 4, `[V2G2-448]` 1, `[V2G2-702]` 1

**สิ่งที่มาตรฐานมองไม่เห็น** (label audit, 6,443 sessions): 104 จาก 222 faulty
sessions ใน test ไม่ติดเกณฑ์ ISO ข้อไหนเลย — `SLAC_FAILURE` 44/44 และ
`SESSION_ABORT` 60/78 (capture หยุดเฉย ๆ timer จึงไม่มีวันหมดเวลา)
สรุป: ISO 15118-2 ครอบคลุมประมาณครึ่งหนึ่งของ fault population นี้

## ตรวจสอบความน่าเชื่อถือของ label (สำคัญที่สุด)

ผลของมาตรฐานลงที่ `SESSION_ABORT` 100% ซึ่งเป็น label ที่อ่อนที่สุด —
`ground_truth.py` ตั้ง SESSION_ABORT เมื่อ session ไม่มี `SessionStopRes`
แต่บนฟลีตนี้ "idle = ไม่มี packet" และเกือบทุก session จบที่ขอบ ring buffer
ดังนั้น "ไม่มี SessionStop" จึงหน้าตาเหมือน "capture หยุด" ทุกประการ

แยก 78 session ตามหลักฐานที่*เกิดขึ้นจริงบนสาย* (`benchmark/session_abort_audit.py`):

| หลักฐาน | sessions | % |
|---|---|---|
| TCP RST | 19 | 24.4% |
| re-SLAC (สายหลุด) | 10 | 12.8% |
| `[V2G2-711]` Ongoing ค้าง | 7 | 9.0% |
| `[8.8.1]` เปิด dialog ใหม่ | 6 | 7.7% |
| `Table 109` request ไม่ได้คำตอบ | 2 | 2.6% |
| `[V2G2-443]` 60 วิไม่มี request | 1 | 1.3% |
| **ไม่มีเลย — แค่ไม่มี SessionStopRes** | **44** | **56.4%** |

สัญญาณเตือนอีกอย่าง: median lead บน 44 session นี้คือ **616–1633 วินาที**
เทียบกับ 0–106 วินาทีบนกลุ่มที่มีหลักฐาน — เป็นลายเซ็นของ fault time
ที่ปักไว้ที่ packet สุดท้ายของไฟล์ ไม่ใช่เหตุการณ์จริง

**ทดสอบโดยตัด 44 session นั้นทิ้งทั้งหมด** (`benchmark/robustness_recheck.py`,
เหลือ 428 sessions / 178 faulty):

| detector | rules | features | recall | สรุป |
|---|---|---|---|---|
| RL | +0.0 | **+8.8** | **+14.6pp** | แรงขึ้น (เดิม +8.2 / +13.5pp) |
| MultiAgent | **+6.7** | +0.0 | **+11.8pp** | ยืน (เดิม +7.1 / +12.6pp) |
| AIAgent | +3.7 | −1.0 | +7.3pp | ยืน |
| AgenticAI | −0.6 | +1.1 | +0.0pp | เท่าเดิม |
| TraditionalAI | +0.0 | **−0.8** | **+0.0pp** | **พัง** (เดิม +0.5 / +1.0, recall +3.2pp) |

**ข้อสรุปหลักยืน แต่ข้อสนับสนุนหนึ่งข้อพัง** — โครงสร้าง rules↔features
คงเดิมเป๊ะ และ RL ยังดีขึ้นกว่าเดิมด้วย แต่ recall ที่ TraditionalAI เคยได้ +3.2pp
มาจาก session ที่ label น่าสงสัยล้วน ๆ บนกลุ่มที่มีหลักฐานจริงมันอิ่มตัวที่ 94.1%
ทุก arm อยู่แล้ว — มาตรฐานไม่ได้เพิ่มอะไรให้มันเลย

## แก้ ground truth แล้ว (เป็น default ใหม่)

`pipeline/ground_truth.py` ไม่ตั้ง `SESSION_ABORT` จากการไม่มี `SessionStopRes`
เพียงอย่างเดียวอีกต่อไป — ต้องมีหลักฐานยืนยัน: TCP RST, re-SLAC, หรือ timer ของ
มาตรฐานหมดเวลา**ขณะที่ยังมี packet เข้ามาต่ออีกอย่างน้อย 20 แถว** (PLC poll เดินที่
~20 Hz แม้ V2G ตายแล้ว แต่ capture ที่จบไปแล้วจะไม่มีอะไรต่อ) ตั้ง
`EV_AI_STRICT_ABORT=0` เพื่อย้อนกลับไป label ชุดเดิมได้

| family | เดิม | ใหม่ | diff |
|---|---|---|---|
| SESSION_ABORT | 264 | **123** | **−141** |
| PROTOCOL_FAILED / SLAC_FAILURE / EV_ERROR / EVSE_FAULT / COMM_FREEZE | — | — | **0 ทุกตัว** |
| **รวม faulty** | **708** | **567** | **−141 (−20%)** |

**141 session (53% ของ family) ไม่ใช่ fault** — เป็น capture ที่จบไปเฉย ๆ
อีก 34 session ที่ยังเป็น fault ถูกย้าย `t_fault` มาที่หลักฐานจริง เร็วขึ้นมัธยฐาน 38 วิ

Re-score ด้วย label ใหม่ (`benchmark/rescore_labels.py` — ไม่ต้อง replay ใหม่
เพราะ label ไม่เข้า feature matrix และ detector ไม่เห็น label ตอน replay):

| detector | rules | features | recall |
|---|---|---|---|
| MultiAgent | **+6.2** | +0.0 | **+12.6pp** |
| RL | +0.0 | **+8.1** | **+14.3pp** |
| AIAgent | +3.2 | −1.0 | +8.2pp |
| AgenticAI | −0.5 | +1.0 | 0.0 |
| TraditionalAI | −0.2 | −1.3 | **0.0** |

**ข้อสรุปหลักไม่เปลี่ยน** โครงสร้าง rules↔features เหมือนเดิมเป๊ะ และ RL แรงขึ้นด้วย
**แต่ TraditionalAI ไม่ได้อะไรจากมาตรฐานเลย** — ที่เคยเห็น +3.2pp มาจาก label ผิดล้วน ๆ

ค่าใช้จ่ายที่ต้องยอมรับ: FAR ขึ้น 1–4 pp ทุกตัว เพราะ 141 session นั้นย้ายไปอยู่ฝั่ง
clean และ detector ก็แจ้งเตือนบางส่วนจริง — capture ที่ถูกตัดกลางคันดู "ผิดปกติ" จริง
แต่ไม่ใช่ความผิดของตู้ชาร์จ

## เทรนใหม่บน label ที่แก้แล้ว (gen2 — ตัวเลขสุดท้าย)

`run_relabeled.ps1` เทรนทั้งสองชุด weights ใหม่บน label ที่แก้ (`train/patch_labels.py`
ใส่ label ใหม่ลง `<split>_sessions.json` โดยไม่ต้อง rebuild matrix) แล้ว replay 3 arms
บน sample เดิม 472 sessions **ข้อระวังที่เจอ:** `run_competition.py` อ่าน label จาก
`sessions/index.json` ไม่ใช่จาก sessions.json ที่ patch — replay รอบแรกจึงให้คะแนน
weights ใหม่บน label เก่า ต้อง re-score ด้วย `rescore_labels.py … index_strict.json`
(ตอนนี้มี `EV_AI_INDEX=index_strict.json` ให้ตั้งตรง ๆ แล้ว)

สามรุ่นเทียบกัน (`benchmark/compare_generations.py`, `results/generations.json`):

| detector | arm | gen1 เก่า/เก่า | gen1r ใหม่/เก่า | **gen2 ใหม่/ใหม่** |
|---|---|---|---|---|
| MultiAgent | base → +rules → +feat | 55.2/62.2/62.2 | 57.2/63.4/63.4 | **57.2/63.4/63.4** |
| AIAgent | | 53.8/58.6/57.5 | 55.4/58.7/57.7 | **54.0/57.7/57.9** |
| RL | | 40.2/40.2/48.5 | 41.7/41.7/49.8 | **49.9/49.9/52.5** |
| TraditionalAI | | 68.0/68.5/69.0 | 70.0/69.8/68.5 | **69.4/69.5/69.2** |
| AgenticAI | | 68.2/67.6/68.5 | 71.8/71.3/72.3 | **72.0/71.5/69.0** |

gen2 สรุป: rules → MultiAgent **+6.2** (+12.6pp recall), AIAgent **+3.7** (+9.3pp), RL **0.0**
features → RL **+2.6** (+3.8pp, FAR ลด), MultiAgent **0.0**, AgenticAI **−2.5** (FAR +10pp)
TraditionalAI ไม่ได้อะไรจากทั้งสองครึ่ง — ยืนยันครั้งที่สาม

**สิ่งที่ retrain บอก (gen1r → gen2):** RL ใน arm baseline ที่ไม่มี ISO เลย
กระโดด 41.7 → 49.9, recall 20.3% → 33.0% **จากการแก้ label อย่างเดียว** —
มากกว่าที่มาตรฐานให้ detector ตัวไหนก็ตามในการทดลองนี้ reward ของมันเคยถูก
คำนวณกับ fault ปลอมที่ปักเวลาไว้หลัง dialog จบไปแล้ว

**คำที่ต้องแก้:** ก่อนหน้านี้ผมรายงานว่า RL ได้ +8.1 จาก ISO features
ตัวเลขจริงหลัง retrain คือ **+2.6** — ส่วนใหญ่ของ "features ช่วย RL" ที่เห็นก่อนหน้า
คือ features กำลังชดเชย label ที่ผิด ทิศทางของข้อสรุปไม่เปลี่ยนเลยทั้งสามรุ่น
(rules → ตัวรวมหลักฐาน, features → ตัวเรียนรู้, ไม่มีใครได้ทั้งคู่)
แต่ขนาดของ features สำหรับ RL ผมประเมินสูงไปเพราะ ground truth ที่ผิด

MultiAgent ได้ค่าเท่ากันเป๊ะระหว่าง gen1r และ gen2 ทุกช่อง — มันไม่มี weights
ให้ retrain จึงเป็น control ที่ยืนยันว่าการ re-score ถูกต้อง

## ทำซ้ำที่ระดับฟลีต — 212 สถานี (`run_fleet_iso_rules.ps1`)

full-fleet pipeline (เสร็จ 12 ก.ย.: 44,198 pcaps, 40,542 sessions, strict label)
เทรนและวัด baseline ไว้แล้วบน held-out **957 faulty / 7,863 clean ใน 45 สถานี
ที่ไม่เคยเห็น** arm `iso_rules` ไม่ต้องเทรนอะไร → replay ครั้งเดียวด้วย weights ของ
ฟลีตเอง (staged sessions ไป `C:\ev_fleet\sessions`, 11 workers, 371.8 นาที)

| detector | base → +rules | Δ ฟลีต | Δ 37 สถานี | recall Δ | SESSION_ABORT (234) |
|---|---|---|---|---|---|
| MultiAgent | 56.3 → 62.5 | **+6.2** | +6.2 | +11.6pp | 36% → **83%** |
| AIAgent | 52.2 → 58.8 | **+6.6** | +3.7 | +13.7pp | 29% → **84%** |
| TraditionalAI | 68.0 → 69.1 | +1.1 | +0.1 | +2.3pp | 81% → 90% |
| AgenticAI | 69.9 → 69.9 | 0.0 | −0.5 | +0.5pp | 74% → 76% |
| RL | 49.5 → 49.5 | **0.0** | 0.0 | 0.0 | 51% → 51% |

**ทำซ้ำได้เกือบเป๊ะ** — MultiAgent ตรงถึงทศนิยม, RL ศูนย์เป๊ะ (ไม่มี rule layer),
`SLAC_FAILURE` ไม่ขยับทุกตัว, ผลลงที่ `SESSION_ABORT` ล้วน ๆ อีกครั้ง
Attribution: AIAgent จับได้ 191 จาก 696 จาก Ongoing timer `[V2G2-711/713]` อย่างเดียว
(abort 97, PROTOCOL_FAILED 50, EVSE_FAULT 40); MultiAgent ได้ 44 abort จาก
message timer `[Table 109]` FAR ขึ้น MultiAgent +0.9pp, AIAgent +4.9pp

**ค่าใช้จ่ายที่โผล่ตอนสเกลใหญ่:** PreCharge `[V2G2-706]` ที่ลดชั้นเป็น graded evidence
ใน StandardsAgent ยังสร้าง false alarm 348 ครั้งต่อ 12 ครั้งที่จับได้ — ควรเอาออก
จาก agent นั้นไปเลย

ผล: `results/fleet_baseline/`, `results/fleet_iso_rules/`, `results/ab_test.json`,
`results/attribution_test.json`

## จุดบอดของมาตรฐาน: `SLAC_FAILURE` — และกฎเดียวที่แก้มันได้

`SLAC_FAILURE` คือ 224 จาก 957 fault ใน holdout (23%) และเป็น family เดียวที่
ISO 15118-2 **อธิบายไม่ได้เลย** เพราะ PLC matching อยู่ใน ISO 15118-**3**
ทั้งสาม arm ที่ผ่านมาจึงขยับ family นี้ไม่ได้สักตัว (ดูตารางข้างบน: 21/21, 7/7, 0/0)
session พวกนี้ไม่มี V2G frame เลยแม้แต่เฟรมเดียว ฟีเจอร์ทั้ง 33 ตัวจึงเป็นศูนย์หมด

เราไม่มีเอกสาร part 3 จึงสร้างกฎจาก**การวัด**แทนการถอดข้อกำหนด
(`core/slac_features.py`, `models/slac_rules.py` — ไม่เพิ่ม vector column แม้แต่คอลัมน์เดียว
weights ของฟลีตจึงโหลดเดิมทุกตัว และเป็น replay ครั้งเดียว):

* match ที่สุขภาพดีได้ `.CNF` ภายใน **7 ms** (p50; p99 = 14 ms จาก 5,129 ครั้ง) —
  ไม่มีการค่อย ๆ แย่ลง charger ตอบแทบจะทันทีหรือไม่ตอบเลย
* 71.9% ของ `SLAC_FAILURE` หยุดที่ `CM_SLAC_MATCH.REQ`, 80.2% ในนั้นไม่เคยเห็น `.CNF`
* ต้อง gate ด้วย "session นี้ยังไม่มี V2G ของตัวเอง" เพราะ connector ข้างกันใช้
  powerline ร่วมกัน เฟรม match ของมันตกมาใน capture เราด้วย — ไม่ gate จะไปคิดเงิน
  session ที่ชาร์จปกติ 685 ครั้ง

### ผล (replay เต็ม 8,820 sessions ยืนยันแล้ว 2026-09-16)

| detector | base | + ISO 15118-2 (773 กฎ) | + SLAC (กฎเดียว) | recall | `SLAC_FAILURE` | FAR |
|---|---|---|---|---|---|---|
| TraditionalAI | 68.0 | 69.1 (+1.1) | **77.0 (+9.0)** | +15.5pp | 21% → **87%** | +0.1pp |
| AIAgent | 52.2 | 58.8 (+6.6) | **62.3 (+10.1)** | +17.2pp | 0% → **72%** | +0.1pp |
| MultiAgent | 56.3 | 62.5 (+6.2) | **65.7 (+9.4)** | +16.2pp | 7% → **75%** | +0.2pp |
| AgenticAI | 69.9 | 69.9 (−0.0) | 71.0 (+1.0) | +0.9pp | 88% → 92% | +0.0pp |
| RL | 49.5 | 49.5 (0.0) | 49.5 (0.0) | +0.0pp | 12% → 12% | +0.0pp |

กฎยิง 199 จาก 8,820 session; median lead ของ AIAgent กระโดดจาก 0.0 เป็น **46.9 วินาที**
(`results/fleet_slac/`, `results/ab_test.json`, `results/attribution_test.json`)

**การคำนวณล่วงหน้าแม่นแค่ไหน** — เทียบกับ replay จริงทั้ง 8,820 sessions:
TraditionalAI / MultiAgent / AgenticAI / RL **ตรงเป๊ะทุกทศนิยม** ส่วน AIAgent
ทำนายไว้ 62.1 ได้จริง 62.3 (+0.13) — สูงกว่าตามที่ประกาศไว้ว่าเป็น lower bound พอดี

**กฎเดียวที่วัดเอาเอง ให้ผลมากกว่ากฎ 773 ข้อที่ถอดจากมาตรฐานทั้งเล่ม** — ไม่ใช่เพราะ
มาตรฐานไม่ดี แต่เพราะ part 2 พูดถึง family ที่ใหญ่ที่สุดของฟลีตนี้ไม่ได้เลย

### ทำไมคำนวณแทน replay ได้ (และยังคง replay อยู่ดี)

กฎ SLAC เป็น early return ล้วน ๆ ทุกตัว → alert แรกใหม่ = `min(alert เดิม, เวลากฎยิง)`
ตรวจจากโค้ดจริง: `models/traditional.py:51` (Layer 0b เหนือกฎ DIN ทุกข้อ),
`models/multi_agent.py:172` (bump 0.95 = `CRIT` พอดี และ `bump()` cap ที่เพดานของผู้เขียนกฎ
sensitivity boost จึงขยับไม่ได้), `models/agentic_ai.py:144` (reflex ก่อน investigation)

`AIAgent` **เป็นข้อยกเว้น และเหตุผลที่ผมให้ไว้ตอนแรกผิด** ผมอ้างว่า session ที่ไม่มี V2G
ทุก tool ลงหลักฐานใน family เดียว (`comm`) เส้นทาง "ต้อง 2 family" จึงไม่มีทางเข้าเงื่อนไข
แต่ evidence board **ไม่ได้ลืมเร็วขนาดนั้น** — หลักฐานสลายตัวด้วย half-life 20 วินาที
session ที่ SLAC สะดุดแล้ว*ต่อติด* จึงพาหลักฐาน `comm` ที่ยังไม่ตายเข้าสู่เฟส V2G
แล้ว anomaly tool ก็เติม family ที่สองให้ → ยิงก่อนเวลาที่คำนวณไว้

วัดจริง: 212 จาก 8,820 session (2.4%) เข้าเส้นทางนี้ได้ และ **ไม่มีสักตัวที่เป็น
`SLAC_FAILURE`** (family นี้ไม่มี V2G ตามนิยาม) ตัวเลข per-family ทั้งหมดจึงไม่กระทบ
มีผลเฉพาะคะแนนรวมของ AIAgent ซึ่งต้องอ่านว่าเป็น **lower bound** จนกว่า replay จะจบ

ทางที่เหลืออีกสองทางเป็น critical จริง: match ค้าง ≥10 s (0.96) และ restart ครบ 3 ครั้ง
(0.5 + 0.15×3 = 0.95 = `CRITICAL` พอดี)

`benchmark/project_slac_arm.py` เขียน state machine ขึ้นใหม่เป็นอันที่สอง (ไม่ import
`SlacTracker`) เพื่อให้การตรงกันแปลว่าโค้ดสองชุดอ่านเฟรมเดียวกันได้เหมือนกัน และ
`benchmark/slac_wait_sweep.py` ซึ่งเป็นชุดที่สาม ให้ตัวเลขที่ W=10 ตรงกันทุกหลัก (199 fires)

### พารามิเตอร์ W ถูกเลือกบน holdout — และมันไม่สำคัญเท่าไหร่

ต้องรายงานตามตรง: W = 10 วินาที ถูกเลือกจาก cost curve ที่วัดบน **holdout** ซึ่งคือ
test-set selection การ sweep ทั้งช่วงจึงจำเป็น (`results/slac_wait_sweep.json`):

| W (s) | 1 | 2 | 5 | 10 | 20 | 30 | 45 | 60 |
|---|---|---|---|---|---|---|---|---|
| mean Δ score | +6.24 | +6.18 | +6.08 | **+5.88** | +5.51 | +5.15 | +4.74 | +0.38 |
| clean fires | 46 | 46 | 35 | 31 | 19 | 15 | 1 | 1 |

แบนราบตลอดช่วง 1–45 วินาที: ค่าที่ดีที่สุดบน holdout (W=1) ดีกว่าค่าที่ใช้จริงแค่
**+0.36 คะแนน** แปลว่าการเลือกพารามิเตอร์บน test set แทบไม่ได้ซื้ออะไรเลย สัญญาณต่างหาก
ที่ทำงาน ส่วนที่ W=60 พังเพราะ `IDLE_GAP_S=60` ใน `sessionize.py` ตัด session ทิ้งก่อน —
เป็น artifact ของการตัด session ไม่ใช่พฤติกรรมรถ

replay ตัวจริง (`run_fleet_slac.ps1`, 155 นาที) ยืนยันแล้ว และเพราะมัน bank
ผลทีละ connector ลง checkpoint เราตรวจได้ระหว่างทางเลย ไม่ต้องรอจบ
(`benchmark/check_projection_vs_replay.py`) — ผลสุดท้าย 7,577 sessions ที่ตรวจได้ระหว่างทาง:
TraditionalAI / RL / AgenticAI / MultiAgent ตรง **100.00%** ทุก session,
AIAgent 7,568/7,577 (0.12%) ทุกเคสที่ต่างคือ replay ยิง*เร็วกว่า*ที่ทำนาย ตามกลไก 2.4% ข้างบน

## เร่ง inference (ผลลัพธ์เท่าเดิมทุกบิต)

`models/fast_infer.py` เปลี่ยน tree traversal เป็น vectorized เดินทุกต้นพร้อมกัน
วนตามความลึกแทนจำนวนต้น: XGB **7.7×**, IForest **7.5×**, end-to-end **1.49×**
(วัด A/B เงื่อนไขเดียวกัน 949 → 638 µs/event) เก็บ loop เดิมเป็น
`margin_ref`/`score_ref` และ `tests/test_fast_infer_equivalence.py` ยืนยัน
`0/3000 differ` ทั้งสอง arm

กับดักสองข้อที่ต้องระวัง — ต้องใช้ `cumsum` ไม่ใช่ `sum` (ลำดับการบวก) และต้อง
สะสมใน **float32** ไม่ใช่ float64 เพราะ NEP 50 ทำให้ `0.0 + np.float32` เป็น
float32 โค้ดเดิมจึงบวกใน float32 ตลอด การใช้ float64 แม่นกว่าแต่ผิด (คลาด 5e-6)

รายงานฉบับเต็ม: [iso15118_ablation_report.html](iso15118_ablation_report.html)
ข้อมูลดิบ: `results/{ab,attribution}_test_s250.json`,
`results/iso_label_audit.json`, `results/iso_evidence.json`
