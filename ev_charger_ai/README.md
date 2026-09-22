# EV Charger Fault-Detection AI Competition (EGAT DC Chargers)

ระบบตรวจจับปัญหาระหว่างการชาร์จรถ EV จาก log การสื่อสาร DIN 70121 (V2G) ของตู้ชาร์จ DC
พัฒนา AI 5 สถาปัตยกรรมแข่งกันบน benchmark เดียวกัน: **ใครตรวจเจอปัญหาได้ก่อนและมากที่สุด**

## ข้อมูล

- pcap จากตู้ชาร์จ 16 สถานี × 2 หัวชาร์จ (3,076 ไฟล์, 7.1 GB) ใน `F:\pcap_downloads`
- ภายในเป็น HomePlug AV (SLAC/PLC), V2GTP, และ DIN 70121 EXI messages
  (SessionSetup → CableCheck → PreCharge → CurrentDemand loop → SessionStop)
- แปลงเป็น telemetry stream ด้วย tshark + V2G dissector → sessions พร้อม label

## นิยาม "ปัญหา" (Ground Truth — อิงสเปค DIN 70121)

| Family | ความหมาย |
|---|---|
| `PROTOCOL_FAILED` | ResponseCode `FAILED_*` เช่น `FAILED_SequenceError` |
| `EVSE_FAULT` | `EVSE_Malfunction` / `EVSE_EmergencyShutdown` |
| `ISOLATION_FAULT` | ฉนวนรั่ว (IsolationStatus = `Fault`) |
| `EV_ERROR` | รถรายงาน error เช่น `FAILED_ChargerConnectorLockFault` |
| `SESSION_ABORT` | จบ session โดยไม่มี SessionStop (สายหลุด/สื่อสารตาย/TCP RST/re-SLAC) |
| `SLAC_FAILURE` | จับคู่ PLC ไม่สำเร็จ ไม่เกิด V2G dialog |
| `COMM_FREEZE` | dialog ค้าง >5 วิ ระหว่างจ่ายไฟ หรือ CableCheck ค้าง >60 วิ |

Session ที่จบปกติ (SessionStop สมบูรณ์ ไม่มี fault marker) = clean

## ผู้แข่งขันทั้ง 5

1. **Traditional AI** (`models/traditional.py`) — rule engine ตามสเปค + Isolation Forest
   (unsupervised) + XGBoost (supervised, GPU) พร้อม threshold คงที่ที่ calibrate ครั้งเดียว
2. **RL** (`models/rl_detector.py`) — Deep Q-Network แบบ optimal stopping (WAIT/ALERT)
   เทรนด้วย fitted Q-iteration บน GPU, reward = ตรวจเจอเร็ว + ไม่แจ้งเตือนผิด
3. **AI Agent** (`models/ai_agent.py`) — agent เดี่ยวแบบ perceive→reason→act เลือกใช้
   tools เอง (spec checker, trend analyzer, comm health, LSTM-Autoencoder, GRU forecaster)
   สะสมหลักฐานบน evidence board แล้ว fuse ด้วย noisy-OR
4. **Agentic AI** (`models/agentic_ai.py`) — goal-driven autonomy: ตั้ง expectation
   รายเฟส, เปิด "investigation" เมื่อผิดคาด, มี station memory ปรับ baseline รายสถานี
   ออนไลน์, reflection หลังจบ session
5. **Multi-Agent** (`models/multi_agent.py`) — ทีม specialist 4 ตัว (Power / Battery /
   Protocol / Comms) + Coordinator ทำ cross-confirmation และ focus request บน blackboard

ทุกตัวรับ `FeatureState` เดียวกันทีละ event (ไม่มี lookahead) — แข่งกันที่สถาปัตยกรรมการตัดสินใจล้วนๆ
โมเดล neural (LSTM-AE, GRU, DQN, XGBoost) เทรนบน GPU จาก **สถานี train เท่านั้น**
แล้ววัดผลบน **5 สถานี test ที่ไม่เคยเห็น** (generalization ข้ามสถานี)

## กติกาการให้คะแนน

ต่อ session: นับ alert แรกเท่านั้น
- **Recall** — สัดส่วน faulty session ที่ตรวจเจอทัน (ภายใน fault + 10 วิ)
- **Lead time** — แจ้งก่อนเกิด fault กี่วินาที (cap 120 วิ)
- **FAR** — สัดส่วน clean session ที่แจ้งเตือนผิด
- **Score = 50×Recall + 30×(1−FAR) + 20×Earliness** (เต็ม 100)
- **Head-to-head wins** — ต่อ faulty session ใครเจอก่อนได้ 1 แต้ม (เสมอแบ่งแต้ม)

## โครงสร้างโปรเจกต์

```
ev_charger_ai/
  pipeline/    extract (tshark→CSV), sessionize, ground_truth
  core/        schema, feature_tracker (33 features), stream, metrics
  models/      ผู้แข่งขัน 5 ตัว + nn_tools (LSTM-AE, GRU)
  train/       build_dataset, train_traditional, train_nn_tools, train_rl
  benchmark/   run_competition.py — สนามแข่ง streaming replay
  artifacts/   model weights (.joblib / .pt)
  data/        telemetry/, sessions/, *_steps.npz
  results/     leaderboard + records
```

## Environment (ติดตั้งแล้วบนเครื่องนี้)

```
C:\Users\user1\anaconda3\envs\ev_ai   (Python 3.11)
  torch 2.11 + CUDA 12.8 (RTX 1000 Ada 6GB), xgboost, scikit-learn,
  pandas, pyarrow, matplotlib, tqdm
```

รันทุกอย่างด้วย:

```bash
C:\Users\user1\anaconda3\envs\ev_ai\python.exe
```

## ขั้นตอนรันใหม่ตั้งแต่ต้น (reproduce)

```bash
# 1) แปลง pcap → telemetry CSV (ใช้ tshark, ~1 ชม. ด้วย 14 workers)
python pipeline/extract_all.py
# 2) ประกอบ session + label ground truth
python pipeline/sessionize.py
# 3) สร้าง dataset
python train/build_dataset.py
# 4) เทรนโมเดล (GPU)
python train/train_traditional.py
python train/train_nn_tools.py
python train/train_rl.py
# 5) รันการแข่งขันบน test stations
python benchmark/run_competition.py test
```

## Deploy บน Production Server

- ทุก detector เป็น Python class ที่ implement `Detector.observe(event, features)` →
  ใช้ต่อกับ stream จริงได้ทันที (feed event จาก tshark live capture / OCPP gateway)
- ต้องมี: Python 3.11, PyTorch (CUDA ไม่บังคับตอน inference — CPU ก็รันได้),
  xgboost, scikit-learn, joblib + โฟลเดอร์ `artifacts/`
- ตัวอย่าง live pipeline: `tshark -i <if> -T fields ... | python stream_adapter.py`
  (ใช้ `extract_worker.py` parsing logic เดียวกัน)
- Latency ต่อ event ต่ำ (ดู `wall_seconds` ใน leaderboard) — รองรับ real-time

## ⚠️ ผลการแข่งขันรอบ 2026-08-13 ใช้ไม่ได้

ตารางเดิม (TraditionalAI 70.1 ฯลฯ บน 853 sessions / 5 สถานี) **ถูกยกเลิก**:
การรีวิวพบว่ากฎ re-SLAC ติด label ผิดประมาณครึ่งหนึ่งของ session ที่ถูกเรียกว่า
"faulty" — SLAC frame ที่เห็นเป็นของหัวชาร์จข้าง ๆ ที่ใช้สาย PLC เส้นเดียวกัน
ไม่ใช่สายหลุดของ session นี้ (แก้แล้วใน `pipeline/ground_truth.py` ดู
[[egat-v2g-data-gotchas]])

Label ที่แก้แล้ว 37 สถานี: **6,443 sessions / 708 faulty (11.0%)**
แบ่ง train 27 สถานี (4,534 sessions) / test 10 สถานี (1,909 sessions)

## การทดลองปัจจุบัน: แนบมาตรฐาน ISO 15118-2:2014

เทรน 3 ระบบบนข้อมูล ground truth และ split เดียวกัน ต่างกันแค่ "รู้จักมาตรฐานแค่ไหน"
— `baseline` (33 features, threshold จูนจากข้อมูล) / `iso_rules` (weights ชุดเดิม
+ ISO rule layer) / `iso` (+ 27 ISO conformance features, เทรนใหม่ทั้งหมด)

วิธีรันและสิ่งที่พบ: **[docs/iso15118_experiment.md](docs/iso15118_experiment.md)**
กฎที่ถอดจากมาตรฐาน: `core/iso15118.py`, `core/iso_features.py`, `models/iso_rules.py`
เครื่องมือ: `benchmark/{compare_arms,attribute_alerts,iso_evidence,iso_label_audit}.py`

## ISO 15118-3 continuation (2026-09-17)

The continued review keeps the published benchmark immutable and adds two
opt-in profiles:

- `EV_AI_SLAC_RULE_MODE=normative` applies the public-source SLAC timers;
- `EV_AI_LABEL_PROFILE=iso_reviewed` applies the adjudicated ground-truth
  changes and records censored sessions separately.

The immutable published `index.json` is older than the current `strict` code
path; do not treat those two label snapshots as interchangeable. The report
below separates published, pre-review strict, and ISO-reviewed results.

Start with **[docs/iso15118_3_continuation_report.md](docs/iso15118_3_continuation_report.md)**.
The public-source provenance is in
**[docs/iso15118_3_public_sources.md](docs/iso15118_3_public_sources.md)**,
and every label proposal is dispositioned in
**[docs/iso15118_label_proposal_decisions.md](docs/iso15118_label_proposal_decisions.md)**.
