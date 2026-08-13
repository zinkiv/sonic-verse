# SonicVerse 技术设计文档

> 版本：v0.2（与代码对齐）  
> 日期：2026-08-07  
> 状态：实现现状说明（基于仓库代码整理）

---

## 目录

1. [项目概述](#1-项目概述)
2. [技术架构](#2-技术架构)
3. [项目结构](#3-项目结构)
4. [数据库设计](#4-数据库设计)
5. [API 设计](#5-api-设计)
6. [核心模块设计](#6-核心模块设计)
7. [前端设计](#7-前端设计)
8. [Docker 部署](#8-docker-部署)
9. [配置与环境变量](#9-配置与环境变量)
10. [功能状态与路线图](#10-功能状态与路线图)

---

## 1. 项目概述

### 1.1 项目定位

SonicVerse（音元）是面向个人数字音乐库的元数据管理与增强平台。

定位：**个人音乐资产管理中台**

| 类比产品 | 管理对象 |
|----------|----------|
| Sonarr | 电视剧 |
| Radarr | 电影 |
| BookVerse | 图书 |
| **SonicVerse** | **音乐** |

### 1.2 核心问题

- 音乐文件命名与目录结构混乱
- ID3 / Vorbis / MP4 标签缺失或错误
- 专辑信息、封面缺失
- 艺术家名称不统一
- 多版本曲目难管理

### 1.3 目标用户

- 个人音乐收藏者
- NAS 用户（配合 Plex / Jellyfin / Navidrome）
- 音乐发烧友

### 1.4 当前能力摘要

已落地：扫描入库、曲库浏览、QQ 音乐 / 网易云匹配、封面下载、标签写回、文件上传、中英 i18n、主题切换、单容器 Docker 部署。

未接线或未完成：Organizer API/UI、批量匹配、MusicBrainz 注册进匹配链路、Genre 业务、Alembic 迁移、PostgreSQL/Redis compose。

---

## 2. 技术架构

### 2.1 技术栈

| 层级 | 技术选型 | 说明 |
|------|----------|------|
| 后端框架 | Python 3.11+ + FastAPI | async API |
| ORM | SQLAlchemy 2.0（async） | 启动时 `create_all` 建表 |
| 数据库（默认） | SQLite + aiosqlite | 零配置，数据在 `./data` |
| 数据库（可选） | PostgreSQL | 改 `DATABASE_URL` 即可；无独立 compose 模板 |
| 音频解析 / 写标签 | mutagen | ID3 / Vorbis / MP4 等 |
| 元数据源（已接入） | QQ 音乐、网易云 | 匹配 API 默认 `qqmusic` |
| 元数据源（旁路） | MusicBrainz（`musicbrainz.py`） | 依赖存在，**未注册到 Provider registry** |
| 前端 | Vue 3 + TypeScript + Vite | |
| CSS | TailwindCSS | 页面内联组件；`components/ui` 为空，未用 shadcn-vue |
| 状态 | Pinia（`library` store） | |
| HTTP | Axios | |
| i18n | vue-i18n（zh / en） | |

### 2.2 系统架构

```
┌──────────────────────────────────────────────┐
│  单容器 :7526（Vue dist 由 FastAPI 托管）     │
│  Library / Metadata / Settings               │
│  /api/v1  ·  /covers  ·  /health             │
└──────────────────────┬───────────────────────┘
                       ▼
┌──────────────────────────────────────────────┐
│  FastAPI                                     │
│  tracks · albums · artists · scanner         │
│  matcher · upload · stats · settings         │
└───────┬──────────────┬───────────────┬───────┘
        ▼              ▼               ▼
   Scanner+Pipeline  Matcher+Tagger   Upload
        │              │
        │              ▼
        │        Provider 层
        │     ┌──────────┬──────────┐
        │     │ qqmusic  │ netease  │  (+ musicbrainz 未注册)
        │     └──────────┴──────────┘
        ▼
   SQLAlchemy → SQLite (./data) 或 PostgreSQL
   静态封面 → ./covers → /covers
```

---

## 3. 项目结构

```
sonic-verse/
├── backend/
│   ├── sonicverse/
│   │   ├── main.py                 # FastAPI 入口、CORS、/covers、/health
│   │   ├── api/
│   │   │   ├── dependencies.py
│   │   │   └── routes/
│   │   │       ├── tracks.py
│   │   │       ├── albums.py
│   │   │       ├── artists.py
│   │   │       ├── scanner.py
│   │   │       ├── matcher.py      # match / apply / confirm-local
│   │   │       ├── upload.py
│   │   │       ├── stats.py
│   │   │       └── settings.py     # 只读配置
│   │   ├── core/                   # config, database
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── scanner/                # scanner.py + pipeline.py
│   │   ├── metadata/               # parser.py
│   │   ├── providers/              # base, qqmusic, netease, musicbrainz
│   │   ├── matcher/                # matcher.py, query.py
│   │   ├── tagger/                 # apply 时写盘
│   │   └── organizer/              # 有实现与单测，无 API/UI
│   ├── tests/
│   ├── scripts/
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── views/                  # LibraryView, MetadataView, SettingsView
│   │   ├── stores/library.ts
│   │   ├── i18n/
│   │   ├── composables/useTheme.ts
│   │   ├── router/
│   │   └── components/ui/          # 空目录
│   ├── nginx.conf
│   └── Dockerfile
├── migrations/                     # 规划中的 Alembic 迁移目录
├── configs/                        # 部署 / 共享配置说明
├── scripts/                        # compose / 本地开发辅助脚本
├── docs/                           # DESIGN.md、preview.html
├── music/ · data/                  # data/transfer 为中转目录
├── Dockerfile                      # 前端 + 后端单镜像
├── docker/entrypoint.sh
├── docker-compose.yml
├── .env.example
└── README.md
```

**关键决策**

| 决策 | 选择 | 说明 |
|------|------|------|
| 仓库形态 | Monorepo | 前后端联调简单 |
| Provider | 网易云 / QQ | 中文曲库命中更好；MB 保留未接线 |
| 外部 ID 字段名 | `mbid` | 历史命名；实际存各 provider 的外部 ID（最长 64） |
| 建表方式 | `create_all` + SQLite 补丁 | `migrations/` 已预留；Alembic 尚未接线 |
| 部署 | 单容器 | FastAPI 托管 Vue dist；entrypoint 默认 uid 1000 |

---

## 4. 数据库设计

### 4.1 ER 关系

```
Artist 1──* Album 1──* Track
Artist 1──────────────* Track
Track 1──* ProviderResult
Genre（仅有表，无业务关系）
ScanJob（独立任务表）
```

### 4.2 表结构（与模型一致）

#### Artist

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | String(36) | PK | UUID |
| name | String(255) | NOT NULL, index | |
| sort_name | String(255) | | |
| mbid | String(64) | UNIQUE, NULL | 外部 ID |
| created_at / updated_at | DateTime(tz) | | |

#### Album

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | String(36) | PK | |
| title | String(255) | NOT NULL | |
| artist_id | String(36) | FK → Artist, ON DELETE SET NULL | |
| year | Integer | NULL | |
| mbid | String(64) | UNIQUE, NULL | |
| cover_path | String(512) | NULL | 相对/文件路径；经 `/covers` 访问 |
| created_at / updated_at | DateTime(tz) | | |

#### Track

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | String(36) | PK | |
| title | String(255) | NOT NULL, index | |
| album_id / artist_id | String(36) | FK, SET NULL | |
| track_number / disc_number | Integer | 默认 1 | |
| duration_ms | Integer | NULL | |
| mbid | String(64) | index，**非 UNIQUE** | 可存 `local-confirmed` 等哨兵 |
| file_path | String(1024) | UNIQUE | |
| file_hash | String(64) | index | SHA256 |
| created_at / updated_at | DateTime(tz) | | |

#### Genre

仅有 `id` + `name`（UNIQUE）。无 ORM 关系、无 API、无写入路径。

#### ScanJob

| 字段 | 说明 |
|------|------|
| status | `pending` / `running` / `completed` / `failed` / **`cancelled`** |
| root_path | 扫描根目录 |
| tracks_found / tracks_processed | 进度 |
| error_msg | 可选 |

#### ProviderResult

| 字段 | 说明 |
|------|------|
| track_id | FK → Track |
| provider | 如 `qqmusic` / `netease` |
| provider_mbid | String(64) 外部曲目 ID |
| confidence | 0.0–1.0 |
| metadata_json | 完整候选元数据 |
| applied | 是否已应用 |

### 4.3 存储位置

| 用途 | 默认路径 |
|------|----------|
| SQLite | `./data/database/sonicverse.db`（Docker：`/data/database/`） |
| 音乐文件 | `./music` |
| 封面缓存 | `./data/covers`（Docker：`/data/covers`） |
| 曲库指纹 | `./data/library/music_library_fingerprint.json` |
| 中转目录 | `./data/transfer`（Docker：`/data/transfer`） |
| 日志 | `./logs`（Docker：容器内 `/app/logs`，不挂卷） |

---

## 5. API 设计

- 前缀：`/api/v1`（可配 `API_PREFIX`）
- 认证：当前无鉴权
- 分页：`page` + `page_size`（默认 50，最大 200）
- 排序：列表接口**未实现** `sort` 参数（固定按 title/name + id）
- OpenAPI：`http://localhost:7526/docs`（开发模式后端仍为 `:8000/docs`）
- 健康检查：`GET /health`
- 封面静态：`GET /covers/...`

### 5.1 端点一览

#### Tracks — `/api/v1/tracks`

| Method | Path | 说明 |
|--------|------|------|
| GET | `/tracks` | 列表；支持 `search`、`album_id`、`artist_id`、`issue` 筛选 |
| GET | `/tracks/{id}` | 详情 |
| PUT | `/tracks/{id}` | 更新库内字段 |
| DELETE | `/tracks/{id}` | 删除记录（不删文件） |

#### Matcher — 挂在 tracks 下

| Method | Path | 说明 |
|--------|------|------|
| POST | `/tracks/{id}/match` | 查候选；`provider`: `qqmusic`（默认）\| `netease` |
| POST | `/tracks/{id}/apply` | 应用候选：更新 DB + **写标签** + 拉封面 |
| POST | `/tracks/{id}/confirm-local` | 确认本地元数据（前端暂未调用） |

#### Albums / Artists

| Method | Path | 说明 |
|--------|------|------|
| GET/PUT | `/albums`、`/albums/{id}` | 详情含 artist summary，**不含曲目列表** |
| GET/PUT | `/artists`、`/artists/{id}` | 详情**不含专辑列表** |

#### Scanner — `/api/v1/scanner`

| Method | Path | 说明 |
|--------|------|------|
| POST | `/scanner/scan` | 启动后台扫描 |
| GET | `/scanner/jobs` | 任务列表 |
| GET | `/scanner/jobs/{id}` | 任务详情 |
| POST | `/scanner/jobs/{id}/cancel` | 取消 |
| GET | `/scanner/stats` | 扫描相关统计 |

#### 其它

| Method | Path | 说明 |
|--------|------|------|
| GET | `/stats` | 曲库统计（含 missing_covers、unknown_artists、pending_review 等） |
| GET | `/settings` | 只读运行配置 |
| POST | `/upload` | multipart 上传音频到 `music_path` 并入库 |

### 5.2 未实现（曾在初稿中规划）

- `POST /tracks/batch-match`
- `POST /tracks/{id}/read-metadata`
- `GET /albums/{id}/cover`（改用静态 `/covers`）
- 整组 `/organizer/*`

### 5.3 典型流程：匹配 → 应用

```
POST /api/v1/tracks/{id}/match?provider=qqmusic
  → 返回候选列表（含 confidence）

POST /api/v1/tracks/{id}/apply
  body: { provider, provider_mbid 或候选索引 }
  → Tagger 写文件成功后才 commit DB
  → 可选下载封面到 covers_path
```

---

## 6. 核心模块设计

### 6.1 Scanner + Pipeline

- `AudioScanner`：按扩展名遍历目录（`.mp3 .flac .m4a .ogg .wav .ape`）
- `metadata/parser.py`：mutagen 读标签与内嵌封面
- `pipeline.py`：后台任务、进度、取消、入库、中断任务复位（启动时 `reset_interrupted_jobs`）
- 扫描路径限制在配置的 `music_path` 内

### 6.2 Provider

注册表（`providers/__init__.py`）：

| name | 类 | 状态 |
|------|-----|------|
| `qqmusic` | QQMusicProvider | 已接入，默认 |
| `netease` | NeteaseProvider | 已接入 |
| （未注册） | MusicBrainzProvider | 文件存在，匹配 API 不可选 |

接口要点：`search_track`、封面获取等；外部 ID 统一进 `mbid` / `provider_mbid` 字段。

### 6.3 Matcher

流程：本地曲目信息 → Provider 搜索 → 打分排序 → 返回候选。

打分（当前实现）：

| 维度 | 权重 |
|------|------|
| 标题相似度 | 60% |
| 艺术家相似度 | 25% |
| 时长接近 | 15% |

垃圾标题（含 live/伴奏等标记）会乘以惩罚系数（约 ×0.25）。默认置信度阈值：`match_confidence_threshold = 0.7`。

### 6.4 Tagger

在 `apply` 中调用。按扩展名写 ID3 / Vorbis / MP4 等；写盘失败则不提交库内变更。

### 6.5 Organizer

`FileOrganizer` 支持按 `{artist}/{year} - {album}/{track}. {title}.{ext}` 类模板整理；仅有单元测试，**无 HTTP API、无前端入口**。

---

## 7. 前端设计

### 7.1 路由

| Path | 组件 | 职责 |
|------|------|------|
| `/` | LibraryView | 专辑墙 / 艺术家 / 曲目 Tab + 搜索分页 |
| `/metadata` | MetadataView | 问题曲目、匹配候选、apply、上传、触发扫描 |
| `/settings` | SettingsView | 只读服务端配置、扫描进度/取消、语言与主题 |

无独立 Dashboard / AlbumDetail / ArtistDetail / Scanner / Matcher 页面。

### 7.2 状态与其它

- Pinia：`stores/library.ts`（无独立 scanner store）
- 主题：`useTheme` — system / light / dark；主色 indigo（`#6366f1`）
- i18n：默认中文，可切英文；`localStorage: sonicverse-locale`

---

## 8. Docker 部署

单镜像（前端打进后端，参考 navi-dock）：根目录 `Dockerfile` + `docker-compose.yml`。

| 项 | 说明 |
|------|------|
| 镜像 | `zevenz/sonic-verse:latest` |
| 端口 | `${SERVER_PORT:-7526}:7526` |
| 卷 | `./music:/music`、`./data:/data`（中转目录固定为 `/data/transfer`） |
| 进程用户 | entrypoint 默认 1000:1000（校正 `/data` 后 gosu） |

环境变量模板：根目录 `.env.example`（复制为 `.env`）。无 `SONICVERSE_` 前缀。

访问：

- 界面：http://localhost:7526
- API：http://localhost:7526/api/v1
- OpenAPI：http://localhost:7526/docs

---

## 9. 配置与环境变量

无前缀（见 `core/config.py`）。也可使用 `.env`。Docker 专用项（`SERVER_PORT`）由入口脚本读取，不进入 Settings 模型；进程 uid/gid 由 entrypoint 默认处理，无需在 NAS 面板配置。

| 变量 | 默认 | 说明 |
|------|------|------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/database/sonicverse.db` | DB 连接 |
| `MUSIC_PATH` | `./music` | 音乐根目录 |
| `DATA_PATH` | `./data` | 封面 / DB / library 指纹 / 中转 |
| `TRANSFER_PATH` | `./data/transfer`（Docker：`/data/transfer`） | 中转目录，写死在 data 下 |
| `LOGS_PATH` | `./logs`（Docker：`/app/logs`） | 日志目录，不进 `/data` 卷 |
| `DEBUG` | `false` | 调试日志 |
| `API_PREFIX` | `/api/v1` | API 前缀 |
| `CORS_ORIGINS` | localhost:3000/5173/7526 | CORS |
| `MUSICBRAINZ_USER_AGENT` | SonicVerse/0.1.0 … | MB 用（未接线时影响小） |
| `MATCH_CONFIDENCE_THRESHOLD` | `1.0` | 匹配阈值默认（设置页可覆盖） |
| `SCAN_BATCH_SIZE` | `100` | 扫描批大小 |

运行时限制：无鉴权；settings 只读；上传与扫描限制在 `music_path` 下。

---

## 10. 功能状态与路线图

### 已完成

- [x] Docker 单容器部署（SQLite）
- [x] 音频扫描（后台任务、进度、取消）
- [x] 标签读取与内嵌封面提取
- [x] 曲库 Web 浏览（专辑 / 艺术家 / 曲目）
- [x] QQ 音乐 / 网易云匹配与 apply（含标签写回、封面）
- [x] 文件上传入库
- [x] 统计与只读设置 API
- [x] 前端 i18n、主题切换

### 脚手架 / 部分完成

- [~] MusicBrainz Provider（代码有，未进 registry）
- [~] Organizer（类 + 测试，无 API/UI）
- [~] Genre 表（无业务）
- [~] Alembic（依赖有，无迁移目录）

### 规划中

- [ ] Organizer API + UI
- [ ] 批量匹配
- [ ] 专辑/艺术家详情页
- [ ] MusicBrainz 正式接入匹配
- [ ] PostgreSQL + Redis compose（可选）
- [ ] 与 Navidrome / Plex / Jellyfin 工作流文档或集成
- [ ] 鉴权

---

## 附录 A. 开发命令速查

**后端**

```bash
cd backend
python -m venv .venv
# Windows: .\.venv\Scripts\activate
pip install -e ".[dev]"
uvicorn sonicverse.main:app --reload --port 8000
```

**前端**

```bash
cd frontend
npm install
npm run dev
```

**Docker**

```bash
docker compose up -d
```
