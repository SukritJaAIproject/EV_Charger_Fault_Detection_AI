# Prompt สำหรับส่งให้ Claude

Claude ช่วยรับช่วงงาน iMPS Fault Detection ต่อจาก Codex โดยเริ่มจากอ่านไฟล์ `00_READ_ME_FIRST.md` และ `01_DETAILED_HANDOFF_TH.md` ใน ZIP นี้ทั้งหมดก่อนลงมือ

บริบทสำคัญ:

- งานมีสอง release จาก codebase เดียวกัน: 1.1.0 (`สานต่องาน AI ตรวจจับ Charger Fault`) และ 1.2.0 (`ต่อยอด AI models for charger fault` / chat `AI models for charger fault detection 11`)
- ฟีเจอร์/UI/workflow เหมือนกัน ความต่างหลักคือ snapshot, labels, model artifacts และผล benchmark
- release 1.2.0 เป็น source ปัจจุบันและใช้ benchmark v4 ที่เสร็จแล้ว 8,820 sessions / 5 detectors / 91 checkpoints
- ห้าม rerun หรือ resume benchmark v4 โดยไม่มีเหตุจำเป็น เพราะผลครบและ valid แล้ว
- Offline Setup ของทั้งสอง release พร้อมใช้
- Online Setup ถูก build แล้ว แต่ payload URL ปัจจุบันตอบ 404 ต้อง upload `.nsis.7z` ไป GitHub Release ที่ tag/ชื่อไฟล์ตรงกับ manifest แล้วจึงทดสอบ Online Setup
- working tree ยังมี modified/untracked files และยังไม่ได้ commit งานชุดนี้
- ทั้งสองรุ่นใช้ app ID/product name เดียวกัน จึงติดตั้งคู่ขนานไม่ได้

ลำดับงานที่แนะนำ:

1. ตรวจ `SHA256SUMS.txt` และ `FILE_INVENTORY.csv`
2. อ่าน source snapshot ใน `source/current_working_tree`
3. ตรวจ `benchmark_v4/results`, `benchmark_v4/logs`, `benchmark_v4/checkpoints_original_v4` และ model snapshots
4. ตรวจ release manifests ของ 1.1.0/1.2.0
5. ช่วยวาง/ดำเนินการ release ต่อจากจุดนี้ โดยเริ่มที่การแก้ P0 เรื่อง Online payload 404 และทำ clean-machine QA
6. ก่อนแก้ source ให้ตรวจ working tree จริงที่ `C:\Users\user1\Documents\GitHub\IMPS-Project` และรักษาการเปลี่ยนแปลงเดิมทั้งหมด

โปรดรายงานสิ่งที่ตรวจพบก่อนแก้ไข และอย่าเริ่ม process benchmark ซ้ำหรือหยุดงาน AI อื่น

