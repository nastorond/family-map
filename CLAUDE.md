# 가계도 웹 (Family Tree)

복잡한 집안 가계도를 쉽게 보기 위한 웹 서비스. 가족 구성원이 서로를 등록하면서 가계도를 넓혀 나간다.

## 범위

- 1차 사용자는 **집안 사람만**. 외부 공개 서비스는 나중에 검토한다.
- 회원가입과 연결은 **관리자(개발자 본인)가 승인**해야 반영된다. 자동 매칭이나 자동 병합은 하지 않는다.
- 나중에 여러 집안을 받을 가능성이 있으므로, 처음부터 데이터에 `family_group` 개념을 넣어둔다.

## 기술 스택

| 항목 | 결정 |
|---|---|
| 형태 | **PWA** (모바일 우선 웹, manifest와 아이콘을 넣어 홈 화면에 추가 가능) |
| 백엔드 | **Python + Flask** (FastAPI/Django는 검토 후 제외. Django는 이 규모에 무겁고, FastAPI는 API 중심이라 템플릿 방식에 덜 맞음) |
| 화면 | 서버 렌더링 Jinja 템플릿 + **htmx**. SPA(React 등)와 빌드 도구는 쓰지 않는다 |
| 가계도 시각화 | D3 기반 가계도 JS 라이브러리 하나를 정적 파일로 포함 |
| DB | **SQLite** (볼륨 마운트한 파일 하나) |
| 배포 | 집 **NAS에 Docker 컨테이너**로 운영 |
| 외부 접속 | **Cloudflare Tunnel** (`cloudflared` 컨테이너). 포트포워딩은 하지 않는다 |

### 배포 구성

- `docker-compose.yml` 하나에 컨테이너 2개를 둔다.
  - `app`: Flask + 템플릿/정적 파일 + SQLite
  - `cloudflared`: 터널
- 프론트와 백엔드를 한 컨테이너에서 서빙한다. 프론트를 다른 곳(Vercel 등)에 따로 두지 않는다.
- 개발 단계에서는 **Quick Tunnel**(`*.trycloudflare.com`)을 쓴다. 주소는 cloudflared가 재시작되면(NAS 재부팅, 컨테이너 재시작) 바뀐다.
- 가족 전체에 공개할 때 도메인을 사서 Cloudflare에 연결하고 고정 Tunnel로 바꾼다. 앱 코드는 바뀌지 않고 cloudflared 설정만 바뀐다.
- 도메인 없이 고정 주소가 필요해지면 대안은 Tailscale Funnel(`*.ts.net`)이다.
- 개발은 윈도우 PC에서 docker-compose로 로컬 테스트한 뒤 NAS에 배포한다.
- NAS 모델과 아키텍처(x86/ARM)는 아직 확인하지 않았다. 이미지를 빌드할 때 멀티 아키텍처를 고려한다.

### 검토 후 제외한 선택지 (다시 제안하지 말 것)

- **Vercel + Neon**: 가능하지만 데이터를 집 NAS에 두는 쪽으로 결정했다.
- **Vercel 프론트 + NAS에는 DB만**: DB 포트를 인터넷에 노출해야 하고, 서버리스 함수에서 원격 DB로 붙으면 지연과 연결 비용이 크다. 원칙: **DB 앞에는 항상 백엔드가 같이 있어야 한다.**
- **Oracle Cloud 무료 티어**: 2026년 8월 A1 한도가 2 OCPU/12GB로 줄었고, 춘천 리전은 자리가 없다. 유휴 인스턴스 회수 정책도 있다.
- **Render / Supabase / Railway / Fly.io**: 각각 콜드 스타트, 7일 비활성 시 일시정지, 크레딧 부족, 무료 티어 없음.
- **네이티브 앱**: 플랫폼별 개발, 배포, 업데이트 부담 때문에 PWA로 대체했다.
- **Go / Rust**: 검토했지만 Python으로 결정했다.

## 데이터 모델 (최소)

- **Person**: 가계도의 사람 노드. 가입하지 않은 사람, 고인, 아이도 포함한다.
  - `id`, `family_group_id`, `name`, `gender`(male/female, 모를 수 있음), `birth_date`(8자리 YYYYMMDD, 모를 수 있음), `phone`(선택), `is_deceased`, `created_by`
  - 연결된 계정은 `User.person_id` 한쪽에만 저장한다 (양쪽에 두면 어긋날 수 있음).
  - 성별은 호칭 계산(외삼촌/이모 등)에 필요하다.
- **Relation**: 관계는 **두 종류만 저장**한다.
  - `parent_child` (parent_id → child_id), 세부 종류 `kind`: biological(친생, 기본값) / adoptive(입양) / step(의붓)
  - `spouse` (양방향), 상태 `status`: married(혼인 중, 기본값) / divorced(이혼) / widowed(사별)
  - 형제, 삼촌, 사촌, 촌수, 호칭은 저장하지 않고 **계산으로 구한다**.
- **User**: 로그인 계정.
  - `id`, `name`, `birth_date`, `gender`(가입 때 입력값), `person_id`(승인 전에는 없음), `pin_hash`, `status`(pending/approved), `role`(admin/member), `failed_attempts`, `locked_until`
  - 로그인은 User의 이름+생년월일로 찾는다. 이 둘은 User 안에서 유일하다.
  - 가입 거절은 User 행을 삭제한다.

고려할 경우: 재혼, 입양, 생년월일을 모르는 고인, 같은 사람이 중복으로 등록되는 경우(예: 형제가 각자 "엄마"를 등록).

## 핵심 흐름

1. **가입/로그인**: 이름 + 생년월일(8자리) + PIN.
   - 생년월일은 비밀값이 아니므로 **PIN이 반드시 필요**하다.
   - 신규 가입은 `pending` 상태가 된다. 관리자가 승인하면서 기존 Person 노드에 연결할지, 새 노드를 만들지 정한다.
2. **가족 등록**: 로그인한 사용자가 이름, 성별, 생년월일(8자리), 전화번호(선택), 관계를 입력한다. 관계 세부 종류는 기본값(친생, 혼인 중)으로 두고 필요할 때만 바꾼다.
   - 이름과 생년월일이 같은 Person이 이미 있으면 "같은 사람일 수 있음"으로 표시만 한다.
   - 같은 사람으로 병합할지는 **관리자가 확정**한다.
   - 가계도의 아무 사람 화면에서 "이 사람의 부모/배우자/자녀 추가"로 등록한다. 홈은 내 화면이다.
   - 저장 전에 중복 후보를 보여주고, 사용자가 "이 사람으로 연결" 또는 "다른 사람이에요, 새로 추가"를 고른다. 후보 기준: 이름+생년월일 같음, 또는 이름이 같고 어느 한쪽 생년월일을 모름.
   - 친생 부모는 2명까지. 자손을 부모로(조상을 자녀로) 거는 순환은 막는다.
   - 형제자매 추가: 형제 관계는 저장하지 않고 대상의 부모 밑에 자녀로 넣는다. 부모가 둘이면 "둘 다 같음 / 한쪽만 같음"을 고른다. 부모가 없으면 부모 두 명(이름 모르면 "이름 모름")을 함께 만든다.
   - 형제자매 호칭(형/오빠/누나/언니/남동생/여동생)은 성별과 생년월일로 계산한다. 하나라도 모르면 "남자 형제/여자 형제/형제자매".
3. **관리자 화면**: 가입 승인/거절, 계정과 Person 연결, 중복 노드 병합.
4. **가계도 보기**: **나를 중심으로** 위아래 세대를 펼쳐 보는 방식. 이후 촌수와 호칭 표시("나에게 외삼촌")를 추가한다.
   - 홈(`/`)은 가계도(`/tree`)다. 카드를 누르면 그 사람 중심으로 다시 그린다(`/tree?main=<id>`).
   - family-chart 제약: 부모는 최대 2명만 그린다(친생 > 입양 > 의붓 순). 성별이 꼭 있어야 해서, 모르면 배우자/공동부모의 반대 성별(없으면 남)로 배치하고 카드는 회색으로 칠한다.
   - family-chart는 카드 문구를 innerHTML로 넣는다. 카드에 표시하는 값은 `static/tree.js`의 `esc()`로 반드시 이스케이프한다.
   - 우리 CSS에서 `.card` 클래스 이름은 쓰지 않는다 (라이브러리와 충돌). 상자 스타일은 `.panel`.

## 권한

- 승인된 사용자는 전체 가계도를 볼 수 있다.
- 일반 사용자는 본인과 자기가 등록한 사람만 수정할 수 있다.
- 관계 추가(누군가의 부모/배우자/자녀 등록)는 승인된 사용자 누구나 할 수 있다.
- 관리자는 전부 수정할 수 있다.

## 보안 / 운영

- 가족의 이름, 생년월일, 전화번호가 인터넷에 열린 서버에 있다는 점을 전제로 짠다.
- PIN 해시 저장, **로그인 5회 실패 시 잠금**은 1차 버전부터 넣는다.
  - PIN은 숫자 6자리. 5회 실패하면 30분 잠금, 관리자가 바로 풀 수 있다.
- 모든 POST에 CSRF 토큰(Flask-WTF), 세션 쿠키는 HttpOnly + SameSite=Lax + Secure(터널 뒤 https).
- 컨테이너는 non-root로 실행한다. NAS의 다른 볼륨은 마운트하지 않는다.
- SQLite 파일은 NAS 백업 기능으로 매일 다른 위치에 복사한다.
- 외부 공개 서비스로 넓힐 경우 개인정보보호법(타인 정보를 동의 없이 등록하는 문제)을 검토해야 한다.

## 1차 버전 목표

- [x] 가입(이름, 생년월일, PIN) + 승인 대기
- [x] 관리자 승인 화면 (Person 연결/생성)
- [x] 가족 등록 (부모, 자녀, 배우자) + 중복 후보 표시
- [ ] 관계 수정/삭제, 사람 삭제
- [ ] 관리자 중복 노드 병합
- [x] 나 중심 가계도 보기 (family-chart 0.9.0 + d3 7.9.0, `app/static/vendor/`에 정적 파일로 포함)
- [x] PIN 5회 실패 시 잠금
- [ ] PWA manifest, 아이콘
- [ ] Dockerfile + docker-compose.yml (app + cloudflared Quick Tunnel) — 작성만 함, Docker로 아직 실행 안 해봄

## 개발 실행

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest -q
$env:FLASK_DEBUG=1; $env:COOKIE_SECURE=0; .\.venv\Scripts\flask --app wsgi create-admin
$env:FLASK_DEBUG=1; $env:COOKIE_SECURE=0; .\.venv\Scripts\flask --app wsgi run
```

- DB 파일은 기본으로 `instance/family.db`. `DATABASE_PATH`로 바꿀 수 있다.
- 테이블은 앱 시작 때 `create_all`로 만든다. 마이그레이션 도구는 아직 없다 (스키마가 바뀌면 그때 Alembic 도입 검토).
- Docker: `.env.example`을 `.env`로 복사하고 `SECRET_KEY`를 채운 뒤 `docker compose up -d --build`, 관리자 생성은 `docker compose exec app flask create-admin`, 터널 주소는 `docker compose logs cloudflared`.

## 개발자 정보

- 메인 개발 환경은 윈도우 데스크톱이다.
- Python, C++ 경험이 있고, Django와 프론트엔드도 써봤다.
- 설명은 직설적으로, 과장 없이 한다.
