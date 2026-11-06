# ringkas — Claude Code ingat yang kemarin. Nol token Claude.

[![tests](https://github.com/OcangAmin/ringkas/actions/workflows/test.yml/badge.svg)](https://github.com/OcangAmin/ringkas/actions/workflows/test.yml)
![license](https://img.shields.io/badge/license-MIT-blue)
![python](https://img.shields.io/badge/python-3.9%2B-blue)

[English](README.md) · **Bahasa Indonesia**

*ringkas* mengubah sesi Claude Code Anda menjadi catatan harian dan mingguan yang pendek, ditulis oleh model **gratis** (Gemini, atau model lokal lewat Ollama). Tanya *"kemarin kita ngapain?"* dan Claude membaca catatannya, bukan menebak.

- **Nol token Claude untuk meringkas.** Kuota Claude Anda untuk bekerja, bukan untuk mencatat.
- **Tidak ada yang disuntikkan ke sesi.** Catatan hanya dibaca saat Anda bertanya. Biaya per sesi: deskripsi satu baris skill (±60 token).
- **Tanpa daemon, tanpa cron.** Satu hook SessionStart yang langsung selesai dan mengejar hari yang terlewat di latar.
- **Privasi didahulukan.** Hanya teks percakapan yang diringkas (bukan keluaran alat, bukan berkas yang dibaca alat); pesan soal uang, kesehatan, atau kredensial dilewati; kunci API dan token disamarkan.

## Masalahnya

Setiap sesi Claude Code baru mulai dari nol. Plugin memori memperbaikinya, tapi kebanyakan meringkas memakai Claude sendiri dan memuat memorinya ke setiap sesi, jadi Anda membayar "ingatan" di setiap prompt.

ringkas mengingat sekali sehari dengan model gratis dan menyimpan catatannya di disk sampai Anda butuh.

## Hasilnya

`~/.claude/ringkas/daily/2026-11-06.md` (contoh dengan proyek karangan):

```markdown
# 2026-11-06 (Friday)
## Dikerjakan
- [shop-api] Memperbaiki race condition checkout: row lock di `orders/service.py`, uji lulus
- [shop-api] Menambah `scripts/backfill_totals.py` dan menjalankannya di staging
- [blog] Draf "Postgres locks in 5 minutes", gambar dipindah ke `static/img/locks/`
## Keputusan
- [shop-api] Retry tetap di queue worker, bukan di HTTP handler
## Belum selesai
- [blog] Koreksi dan terbitkan hari Senin
## Dilewati
- 1 bagian sensitif
```

Besok paginya:

> **Anda:** kemarin kita sampai mana?
> **Claude:** *(membaca catatan)* Tanggal 6 Nov Anda memperbaiki race checkout di shop-api dan menjalankan backfill di staging. Artikel blog soal Postgres locks sudah draf; koreksi dan terbit direncanakan Senin.

Setiap minggu (bawaan Senin) catatan harian tiap minggu yang sudah lewat digabung ke satu `weekly/<tanggal>.md` lalu yang harian dihapus, jadi foldernya tetap kecil.

## Cara kerja

```
 Sesi Claude Code dimulai
          │
          ▼
 1. hook: ringkas.py wake  ──► langsung selesai, tanpa keluaran
          │ (latar)
          ▼
 2. cari hari yang belum diringkas (dalam masa simpan transkrip Anda)
          │
          ▼
 3. per hari: ambil teks percakapan semua proyek → lewati topik sensitif
    → samarkan rahasia → ringkas dengan Gemini / Ollama → daily/YYYY-MM-DD.md
          │
          ▼
 4. pada hari rangkuman: catatan harian → weekly/YYYY-MM-DD.md, harian dihapus
```

Saat Anda bertanya soal pekerjaan sebelumnya, skill `ringkas` memberi tahu Claude catatan mana yang dibuka.

## Dibandingkan plugin memori lain

Per Nov 2026, berdasarkan README dan kode masing-masing proyek; detail bisa berubah.

| | **ringkas** | claude-mem | remember | tanpa plugin |
|---|---|---|---|---|
| Peringkas | Gemini gratis atau endpoint OpenAI-compatible (mis. Ollama lokal) | Claude (Haiku) lewat langganan Anda secara bawaan; Gemini/OpenRouter opsional | `claude -p` (Haiku) | — |
| Kuota Claude untuk memori | **0** | ya, secara bawaan | ya | 0 |
| Tambahan di setiap sesi | ±60 token (deskripsi skill) | observasi terbaru disuntik di awal | berkas memori disuntik di awal | 0 |
| Hook | 1 (SessionStart) | 11 | 4 | 0 |
| Proses latar | singkat, sekali per awal sesi | layanan worker (Bun) + SQLite/Chroma yang hidup terus | tidak ada | tidak ada |
| Dependensi | pustaka standar Python 3.9+ | Node, Bun, uv | Python, bash, jq | — |
| Yang keluar dari komputer | teks percakapan tersaring, ke peringkas pilihan Anda | observasi alat, ke peringkas | potongan transkrip, ke Claude | tidak ada |

Pilih claude-mem kalau ingin pencarian semantik atas semuanya; pilih ringkas kalau ingin catatan yang murah, senyap, dan mudah dibaca.

## Pasang

```bash
claude plugin marketplace add OcangAmin/ringkas
claude plugin install ringkas@ringkas
```

Lalu beri kunci Gemini gratis (buat di <https://aistudio.google.com/apikey>) di lingkungan tempat Claude Code dijalankan, mis. di `~/.bashrc` atau `~/.zshrc`:

```bash
export GEMINI_API_KEY="kunci-anda"
```

Selesai. Saat sesi berikutnya dimulai, hari-hari yang sudah ada langsung diringkas. Cek dengan:

```bash
python3 "$(ls -d ~/.claude/plugins/cache/ringkas/ringkas/*/ | sort -V | tail -n 1)ringkas.py" status
```

Jalan di Linux, macOS, dan Termux (Android). Windows belum diuji.

### Semuanya tetap lokal (Ollama)

`~/.claude/ringkas/config.json`:

```json
{ "provider": "openai", "openai_base_url": "http://localhost:11434/v1", "openai_model": "llama3.1" }
```

Endpoint OpenAI-compatible apa pun bisa (OpenRouter, LM Studio, vLLM…). Isi `OPENAI_API_KEY` bila perlu.

Model lokal kecil punya jendela konteks kecil (bawaan Ollama hanya beberapa ribu token dan diam-diam memotong prompt yang lebih panjang). Naikkan (`OLLAMA_CONTEXT_LENGTH=32768 ollama serve`) atau kirim lebih sedikit teks per hari (`"max_chars_per_day": 8000`).

## Privasi

- **Hanya teks percakapan** (pesan Anda dan jawaban Claude) yang diambil. Pemanggilan alat, keluaran alat, gambar, dan transkrip sub-agent tidak pernah dikirim. Jawaban Claude tetap bisa mengutip potongan kode atau keluaran, dan nama folder proyek dipakai sebagai label, jadi anggap catatan ini sebagai "apa yang kita bicarakan".
- **Topik sensitif dilewati.** Pesan yang memuat kata dari `~/.claude/ringkas/sensitive-words.txt` diganti penanda, begitu juga jawaban Claude atasnya. Daftar bawaan mencakup kredensial, uang, dan kesehatan dalam bahasa Inggris dan Indonesia, termasuk akhiran (`salary`/`salaries`, `saldo`/`saldonya`). Silakan diedit.
- **Rahasia disamarkan** sebelum dikirim: kunci privat, `sk-…`, `AIza…`, `ghp_…`, `tskey-…`, JWT, `Bearer …`, `*_KEY=`, `token:`, `--password x`.
- **Abaikan seluruh proyek** dengan `"ignore_projects": ["*klien*"]`.
- **Perhatian:** Google boleh memakai data yang dikirim ke Gemini *tingkat gratis* untuk meningkatkan produknya. Untuk pekerjaan rahasia, pakai kunci Gemini berbayar atau model lokal.

## Pengaturan

`~/.claude/ringkas/config.json` (opsional); setiap kunci juga bisa diisi lewat `RINGKAS_<KUNCI>` (mis. `RINGKAS_LANGUAGE=id`). Kalau Anda memakai `CLAUDE_CONFIG_DIR`, semuanya disimpan di sana, bukan di `~/.claude`.

| Kunci | Bawaan | Arti |
|---|---|---|
| `provider` | `"gemini"` | `"gemini"` atau `"openai"` (endpoint OpenAI-compatible) |
| `models` | `["gemini-flash-latest", "gemini-flash-lite-latest"]` | model Gemini yang dicoba berurutan; model yang kena batas dilewati sementara |
| `openai_base_url` / `openai_model` | — | endpoint dan model untuk `"openai"` |
| `language` | `"auto"` | bahasa ringkasan; `auto` mengikuti percakapan |
| `timezone` | `"auto"` | kapan hari Anda mulai dan berakhir, mis. `"Asia/Jakarta"` |
| `weekly_day` | `"monday"` | hari rangkuman mingguan |
| `ignore_projects` | `[]` | pola glob folder proyek yang dilewati |
| `max_chars_per_day` | `40000` | batas teks yang dikirim per hari |

Perintah: `ringkas.py status`, `ringkas.py run --date YYYY-MM-DD [--dry-run]` (dry run menampilkan persis apa yang akan dikirim), `ringkas.py run-pending`.

## Tanya jawab

**Komputer saya mati seminggu.** Sesi berikutnya mengejar setiap hari yang transkripnya masih ada (`cleanupPeriodDays` Claude Code, bawaan 30). Hari yang sudah hilang dicantumkan di bagian "Not recorded" catatan mingguan.

**Gemini kena batas / sedang turun.** Hari itu dicoba lagi nanti (jeda 1, 2, 4, sampai 6 jam). Tidak ada yang hilang selama transkrip masih ada.

**Apakah memperlambat awal sesi?** Tidak. Hook menyalakan proses terpisah dan selesai dalam hitungan milidetik.

**Apakah Claude selalu melihat catatan saya?** Tidak. Catatan adalah berkas di disk; Claude membukanya hanya bila pertanyaan Anda membutuhkannya.

## Lisensi

MIT. Dibuat dengan Claude Code.
