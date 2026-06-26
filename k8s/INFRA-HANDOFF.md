# 인프라 전달 체크리스트 (EKS 적용)

> 본 `k8s/` 폴더는 **앱 이미지에 포함되지 않습니다**(`.dockerignore`로 제외). 인프라팀이 `kubectl`로 적용하는 자료입니다.
> 앱 소스(서버 이미지)는 `app/` + `Dockerfile` + `requirements.txt`만 빌드됩니다.

## 1. 전달 대상 파일
| 파일 | 용도 | 적용 |
|------|------|------|
| `k8s/backend-deployment.yaml` / `backend-service.yaml` / `backend-ingress.yaml` | 운영 배포/서비스/인그레스 | `kubectl apply` |
| `k8s/dev/backend-deployment-dev.yaml` 등 | 개발 배포/서비스/인그레스 | `kubectl apply` |
| `k8s/backend-secret.example.yaml` / `dev/backend-secret-dev.example.yaml` | **시크릿 템플릿** (실값 X) | 실값 채워 Secret 생성 |
| `k8s/SECRET-SETUP.md` | 시크릿 키 명세·생성 가이드 | 참조 |
| `k8s/rds/01-init-users.sql` / `02-create-additional-tables.sql` / `README.md` | RDS 초기 사용자/권한 (DBA, 1회) | 최초 1회 적용 |

> ⚠️ 실값 시크릿(`backend-secret.yaml`, `dev/backend-secret-dev.yaml`)은 `.gitignore`라 레포에 없음 — 인프라가 example로부터 직접 생성.

## 2. Secret 키 (env 주입 — backend-secret)
DB 접속(DB_HOST/PORT/NAME/USER/PASSWORD), `APP_SECRET_KEY`(dev/운영 **동일값 필수** — 공유 DB), `JUPYTERHUB_ADMIN_TOKEN`, `JUPYTERHUB_JWT_SECRET`.
- 비민감 설정(URL/리전/버킷/자원 프로파일)은 앱 `config.py` 기본값 + 관리자 **Settings 화면**(DB `system_settings`)에서 관리 — k8s 불필요.

## 3. 이번 릴리스의 연동 정보 변경점 (인프라 작업)
- **DB 스키마**: 신규 컬럼(`resource_ledgers.request_note/assigned_to/starts_at`, `capacity_estimates.status`)은 **앱 기동 시 `schema_upgrade`가 자동 ALTER** → **인프라/DBA 별도 작업 불필요**.
- **Airflow 제거**: 포탈에서 Airflow 기능 삭제. backend-secret/deployment env에 `AIRFLOW_*`가 있으면 **제거**(현재 k8s yaml엔 없음 — 확인만). 앱 DB의 잔존 AIRFLOW 설정은 기동 시 자동 정리됨.
- **신규 시크릿 없음**: 추가로 생성/회전할 Secret 키 없음.
- **이미지 변경**: `:latest` 태그 사용 시 `kubectl rollout restart deployment/<name> -n mlops` 필요(no-op 방지).

## 4. 배포 절차 (요약)
1. (빌드 호스트) `build_and_push_dev.sh` → 이미지 빌드·ECR 푸시
2. (빌드 호스트) `deploy_eks_dev.sh` → `kubectl apply` + `rollout restart`
3. 헬스체크: `/health` 200 확인

## 🔐 보안 백로그 (별도)
운영 레포 옛 커밋 `72fb392`에 과거 실값 노출 이력 → DB_PASSWORD / JUPYTERHUB_ADMIN_TOKEN / JWT_SECRET 회전 권장(`APP_SECRET_KEY` 회전은 전 사용자 비번 재설정 동반 → 점검 시).
