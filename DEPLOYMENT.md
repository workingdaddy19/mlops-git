# MLOps 포탈 — 로컬 실행 & 배포 가이드

운영(prod) 배포 전에 **개발(dev) Pod에 먼저 배포·검증**하는 워크플로우를 포함합니다.

| 구분 | ECR | Namespace | 리소스 이름 | 접속 주소 |
|------|-----|-----------|-------------|-----------|
| 운영(prod) | `891376975666.dkr.ecr.ap-northeast-2.amazonaws.com/mlops/app` | `mlops` | `mlops` | http://mlops.click/ |
| 개발(dev) | `891376975666.dkr.ecr.ap-northeast-2.amazonaws.com/mlops-dev/app` | `mlops` | `mlops-dev` | http://dev.mlops.click/ |

> dev/prod는 **같은 ALB(`shared-alb`)를 host 기반으로 공유**합니다. 앱 코드 수정 없이 도메인만 분리됩니다.

---

## 1. 로컬에서 포탈 실행

### 1-0. 사전 준비 — `.env` 생성
```bash
cp .env.example .env
```
`.env`에서 최소 아래 값을 채웁니다(필수): `SECRET_KEY`, `DB_HOST`, `DB_PASSWORD`, `JUPYTERHUB_JWT_SECRET`.
S3/Athena 기능을 로컬에서 쓰려면 AWS 자격증명(`~/.aws/credentials` 또는 `AWS_*` 환경변수)이 필요합니다.

### 1-A. Windows — 배치 파일 (가장 간단)
```bat
start_backend.bat
```
- `.venv` 자동 생성 → 의존성 설치 → `uvicorn ... --reload` 실행
- 접속: **http://localhost:6080**

### 1-B. 수동 (venv + uvicorn) — macOS/Linux/WSL
```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 6080 --reload
```

### 1-C. Docker Compose (백엔드 + Jupyter + MLflow 동시)
```bash
docker compose up --build backend     # 포탈만
# 또는 전체 스택
docker compose up --build
```
- 포탈: http://localhost:6080 / Jupyter: http://localhost:6888 / MLflow: http://localhost:6050
- AWS 자격증명은 `${USERPROFILE}/.aws`를 컨테이너에 read-only 마운트(`docker-compose.yml`)

### 1-D. 동작 확인
```bash
curl http://localhost:6080/health        # {"status":"ok",...}
```
기본 관리자 계정은 기동 시 자동 시드됩니다(`ensure_default_users`). 로그인 후
좌측 메뉴 **권한 신청 / Management** 등을 확인하세요.

---

## 2. EC2 서버를 통한 Pod 배포

CI 없이 **EC2 빌드/배포 서버(bastion)에서 직접 빌드→ECR 푸시→`kubectl apply`** 하는 방식입니다.

### 2-0. EC2 사전 요건 (최초 1회)
빌드/배포용 EC2에 아래가 준비되어 있어야 합니다.

- **도구**: `docker`, `aws` CLI v2, `kubectl`, (선택) `git`
- **IAM 권한**(EC2 인스턴스 프로파일 권장):
  - ECR: `ecr:GetAuthorizationToken`, `ecr:BatchCheckLayerAvailability`, `ecr:PutImage`, `ecr:InitiateLayerUpload`, `ecr:UploadLayerPart`, `ecr:CompleteLayerUpload`, `ecr:CreateRepository`
  - EKS: `eks:DescribeCluster` + 클러스터 `aws-auth`(또는 access entry)에 해당 IAM 주체가 등록되어 kubectl 권한 보유
- **kubeconfig 설정** (최초 1회):
  ```bash
  aws eks update-kubeconfig --region ap-northeast-2 --name <EKS_클러스터명>
  kubectl get ns mlops          # 연결 확인
  ```

### 2-1. 소스 가져오기
```bash
# git 사용 시
git clone <repo-url> mlops-git && cd mlops-git
# 또는 로컬에서 scp 등으로 EC2에 업로드
```

### 2-1.5. Secret 준비 (최초 1회 / 값 변경 시)
실제 비밀값이 담긴 Secret 파일은 **git에 커밋되지 않습니다**(`.gitignore`). 서버에서 템플릿(`*.example.yaml`)을 복사해 실제 값을 채운 뒤 생성하세요.
```bash
# 운영
cp k8s/backend-secret.example.yaml k8s/backend-secret.yaml
vi k8s/backend-secret.yaml            # <...> 자리표시자를 실제 값으로 교체
# 개발
cp k8s/dev/backend-secret-dev.example.yaml k8s/dev/backend-secret-dev.yaml
vi k8s/dev/backend-secret-dev.yaml
```
> deploy 스크립트가 `k8s/.../backend-secret*.yaml`을 `kubectl apply` 하므로, 위 파일이 서버에 존재해야 합니다.

### 2-2. 개발(dev) 배포 — 운영 전 검증
```bash
chmod +x build_and_push_dev.sh deploy_eks_dev.sh
./deploy_eks_dev.sh                       # latest 태그
# 권장: 이미지 태그를 git 커밋 해시로
./deploy_eks_dev.sh $(git rev-parse --short HEAD)
```
`deploy_eks_dev.sh`가 수행하는 것:
1. dev ECR(`mlops-dev/app`) 생성/확인
2. Docker 빌드 → dev ECR 푸시 (`build_and_push_dev.sh`)
3. `k8s/dev/` 의 Secret / Deployment / Service / Ingress 적용
4. 롤아웃 재시작 + 상태 대기 + `/health` 헬스체크

검증: **http://dev.mlops.click/** 접속 (DNS 등록은 2-4 참고)

### 2-3. 운영(prod) 배포 — dev 검증 통과 후
```bash
chmod +x build_and_push.sh deploy_eks.sh
./deploy_eks.sh
```
(`mlops/app` ECR → `mlops` Deployment → `mlops.click`)

### 2-4. DNS 등록 (dev 최초 1회)
`dev.mlops.click`를 운영과 **동일한 ALB 주소**로 가리키게 합니다(같은 shared-alb 공유).
```
dev.mlops.click  CNAME  k8s-sharedalb-0882a5287f-595901001.ap-northeast-2.elb.amazonaws.com
```
> Route53이면 Alias(A) 레코드로 등록해도 됩니다. ALB 주소는 아래로 확인:
> `kubectl get ingress mlops-dev-ingress -n mlops`

---

## 3. dev / prod 워크플로우 요약

```
코드 수정
  └─ (로컬) start_backend.bat 로 동작 확인
       └─ (EC2) ./deploy_eks_dev.sh        # dev ECR + dev Pod 배포
            └─ http://dev.mlops.click 검증
                 └─ (EC2) ./deploy_eks.sh   # 운영 배포
                      └─ http://mlops.click
```

---

## 4. 운영 명령 모음

```bash
# 상태
kubectl get pods,svc,ingress -n mlops -l app=mlops-dev      # dev
kubectl get pods,svc,ingress -n mlops -l app=mlops          # prod

# 로그
kubectl logs -f deploy/mlops-dev -n mlops                   # dev
kubectl logs -f deploy/mlops -n mlops                       # prod

# 재배포 (같은 latest 태그로 이미지만 갱신)
kubectl rollout restart deployment/mlops-dev -n mlops

# 롤백
kubectl rollout undo deployment/mlops-dev -n mlops

# dev 환경 제거 (전체 정리)
kubectl delete -f k8s/dev/ -n mlops
```

---

## 5. 구성 파일 인덱스

| 파일 | 용도 |
|------|------|
| `Dockerfile` / `docker-compose.yml` | 이미지 빌드 / 로컬 스택 |
| `start_backend.bat` | Windows 로컬 실행 |
| `build_and_push.sh` / `deploy_eks.sh` | **운영** 빌드·배포 |
| `build_and_push_dev.sh` / `deploy_eks_dev.sh` | **개발** 빌드·배포 |
| `k8s/backend-*.yaml` | 운영 매니페스트 |
| `k8s/dev/backend-*-dev.yaml` | 개발 매니페스트 |

---

## 6. 보안 참고

- **공개 저장소 안전 처리**: 실제 비밀값이 담긴 `k8s/backend-secret.yaml`, `k8s/dev/backend-secret-dev.yaml`, `.env` 는 `.gitignore`로 **커밋 제외**됩니다. 저장소에는 자리표시자만 담긴 `*.example.yaml` / `.env.example` 템플릿만 올라갑니다.
- 서버에서는 §2-1.5처럼 템플릿을 복사해 실제 값을 채워 사용하세요.
- 더 안전하게 운영하려면 **SealedSecrets / AWS Secrets Manager(External Secrets)** 도입을 권장합니다.
- dev Secret(`backend-secret-dev`)은 운영 데이터 보호를 위해 **별도 DB(`mlops_dev`)와 별도 `SECRET_KEY`**를 사용하도록 구성했습니다.
