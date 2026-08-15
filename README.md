# SonicVerse 音元

> 让每一首音乐拥有正确的身份

个人数字音乐库元数据管理与增强平台。

更完整的设计说明见 [docs/DESIGN.md](./docs/DESIGN.md)。Docker Hub 说明见 [DOCKERHUB.md](./DOCKERHUB.md)。

## 快速开始

### Docker 部署（推荐）

单容器：前端由后端托管，默认端口 **7526**。

```bash
cp .env.example .env
docker compose up -d --build
```

访问：http://localhost:7526

首次打开会进入**创建管理员**页面；之后需登录才能使用。管理员可在设置里添加普通用户。

API：http://localhost:7526/api/v1  
OpenAPI：http://localhost:7526/docs

**NAS：** 镜像 `zevenz/sonic-verse:latest`。启动时会按 `PUID`/`PGID`（默认 1000）校正 `/data` 属主后再降权运行。群晖面板里填这两项，使其与音乐库/数据目录属主一致。

构建时传入版本号（设置页会显示该值；不传则为 `dev`）：

```powershell
$env:APP_VERSION = "v0.1.0"
docker compose build
docker push zevenz/sonic-verse:latest
```

也可直接：

```bash
docker build --build-arg APP_VERSION=v0.1.0 -t zevenz/sonic-verse:latest .
```

### 开发模式

**后端：**

```bash
cd backend
python -m venv .venv
# Windows: .\.venv\Scripts\activate
# Linux/Mac: source .venv/bin/activate
pip install -e ".[dev]"
uvicorn sonicverse.main:app --reload --port 8000
```

**前端：**

```bash
cd frontend
npm install
npm run dev
```

Vite 将 `/api` 与 `/covers` 代理到 `http://localhost:8000`。

## 功能

- [x] 音频扫描（MP3 / FLAC / AAC / OGG / WAV / APE）与后台任务
- [x] ID3 / Vorbis Comment / MP4 标签读取与写回
- [x] 网易云 / QQ 音乐元数据匹配（查询可选来源，整理两边都查）
- [x] 中转目录整理：匹配后按「歌手名-歌曲名」入库
- [x] Web 管理界面（曲库、元数据、设置、中英 i18n）

## 技术栈

**后端：** Python 3.11+ / FastAPI / SQLAlchemy 2.0（async）/ SQLite（可切 PostgreSQL）/ mutagen

**前端：** Vue 3 + TypeScript / Vite / TailwindCSS / Pinia / vue-i18n

## 环境变量（常用）

无前缀。模板见 [.env.example](./.env.example)。

| 变量 | 默认 | 说明 |
|------|------|------|
| `SERVER_PORT` | `7526` | 对外端口 / 容器内监听端口 |
| `DATABASE_URL` | （空则本地 sqlite） | 配置了 Postgres URL 则用 PostgreSQL，例如：`postgres://user:pass@host:5432/sonic_verse?sslmode=prefer` |
| `MUSIC_PATH` | `./music` / 容器内 `/music` | 音乐目录 |
| `DATA_PATH` | `./data` / `/data` | 封面 / DB / library / 中转 |
| `TRANSFER_PATH` | `./data/transfer` / `/data/transfer` | 中转（固定在 data 下，compose 不配） |
| `LOGS_PATH` | `./logs` / `/app/logs` | 日志（容器内，不挂卷） |
| `APP_VERSION` | `dev`（构建未传时） | 设置页版本；构建：`$env:APP_VERSION="v0.1.0"; docker compose build` |
| `AUTH_SECRET` | （空则写入 `data/.auth_secret`） | 登录令牌密钥，重启后保持登录 |
| `PUID` | `1000` | 容器进程用户 ID（与音乐库/数据目录属主对齐） |
| `PGID` | `1000` | 容器进程组 ID（也接受 `GUID` / `PGUID`） |
| `DEBUG` | `false` | 调试模式 |

完整列表见 [docs/DESIGN.md §9](./docs/DESIGN.md#9-配置与环境变量)。

## 项目结构

```
sonic-verse/
├── Dockerfile               # 前端 + 后端单镜像
├── docker-compose.yml
├── docker/entrypoint.sh
├── .env.example
├── README.md
├── backend/
├── frontend/
└── docs/
```

运行时数据目录（gitignore）：`music/`、`data/`（含 `data/transfer/`）。

## 许可证

[Apache License 2.0](LICENSE)
