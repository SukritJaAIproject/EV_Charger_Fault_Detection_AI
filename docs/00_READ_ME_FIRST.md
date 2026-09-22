# iMPS Fault Detection — Claude handoff package

วันที่จัดทำ: 22 กันยายน 2026 (Asia/Bangkok)

แพ็กเกจนี้จัดทำเพื่อส่งต่องานจาก Codex ให้ Claude ทำต่อ โดยครอบคลุมงานจากสองแชต/สอง release ดังนี้

1. `สานต่องาน AI ตรวจจับ Charger Fault` / Claude chat `AI models for charger fault detection` → release `v1.1.0`
2. `ต่อยอด AI models for charger fault` / Claude chat `AI models for charger fault detection 11` → release `v1.2.0`

## เริ่มอ่านจากตรงไหน

1. อ่าน `01_DETAILED_HANDOFF_TH.md` เพื่อดูสถานะทั้งหมด ข้อสรุป ผล benchmark วิธี build และงานค้าง
2. ใช้ข้อความใน `02_PROMPT_FOR_CLAUDE.md` เป็น prompt เริ่มต้นใน Claude
3. ดู `comparison/imps_fault_detection_feature_comparison_v1.1_v1.2.pdf` สำหรับรายงานเปรียบเทียบ 4 หน้า
4. ตัวติดตั้งอยู่ใน `installers/v1.1.0` และ `installers/v1.2.0`
5. source ที่เปลี่ยน/เพิ่มอยู่ใน `source/current_working_tree`
6. source และผล benchmark v4 อยู่ใน `benchmark_v4`
7. ตรวจความครบถ้วนด้วย `SHA256SUMS.txt` และ `FILE_INVENTORY.csv`

## สถานะสำคัญที่สุด

- `v1.1.0` และ `v1.2.0` มีทั้ง Offline Setup และ Online Setup แล้ว
- Offline Setup เป็นตัวติดตั้งแบบ self-contained และพร้อมใช้โดยไม่ต้องมี Node.js, Python, Wireshark, Npcap หรือ MongoDB บนเครื่องปลายทาง
- Online Setup ถูก build แล้ว แต่ URL payload ที่ฝังไว้ทั้งสองรุ่นยังตอบ `404 Not Found` ณ วันที่จัดทำแพ็กเกจ จึงต้อง upload `.nsis.7z` ไปยัง GitHub Release ตาม tag/ชื่อไฟล์ใน manifest ก่อนแจกใช้งาน
- benchmark v4 เสร็จสมบูรณ์: 8,820 sessions, 5 detectors, 90 connectors, 91 checkpoints; ไม่ต้อง resume หรือ rerun
- ฟีเจอร์/UI/workflow ของสอง release เหมือนกันโดยสาระ ความต่างหลักคือ snapshot ข้อมูล, label distribution, model weights/thresholds และผล benchmark
- ทั้งสอง release ใช้ app ID และ product name เดียวกัน จึงติดตั้งคู่ขนานไม่ได้; รุ่นใหม่จะเขียนทับ/อัปเกรดรุ่นเก่า

## สิ่งที่ตั้งใจไม่ใส่ใน ZIP

ไม่ได้รวม raw tensors/arrays และ session corpus ขนาดหลายสิบ GB เช่น `train_X.npy`, `test_X.npy` และโฟลเดอร์ `sessions` รวมถึง build cache/ไฟล์ซ้ำ (`node_modules`, `.next*`, `.desktop-build`, `win-unpacked`, smoke extraction directories) เพราะตัวติดตั้ง ผล benchmark checkpoints source และ model snapshots ที่จำเป็นถูกรวมไว้แล้ว ตำแหน่งไฟล์ต้นฉบับทั้งหมดบันทึกใน `01_DETAILED_HANDOFF_TH.md`

