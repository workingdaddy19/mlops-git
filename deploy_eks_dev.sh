#!/bin/bash
# ============================================================
# [개발용] EKS 배포 스크립트 (운영 배포 전 검증용)
# AWS Account : 891376975666
# Region      : ap-northeast-2
# Namespace   : mlops               (운영과 동일 ns, 리소스는 -dev 접미사)
# ECR         : mlops-dev/app
# Host        : dev.mlops.click
# ============================================================
set -e

IMAGE_TAG="${1:-latest}"

echo ""
echo "======================================================"
echo "  MLOps [DEV] EKS 배포 시작 (tag=${IMAGE_TAG})"
echo "======================================================"

# ─────────────────────────────────────────────
# STEP 0. 사전 점검 — dev Secret 파일 존재 확인
#   실제 값이 담긴 Secret 은 보안상 git 제외(.gitignore)되어
#   새로 clone 한 서버에는 *.example.yaml 만 존재한다.
# ─────────────────────────────────────────────
DEV_SECRET="k8s/dev/backend-secret-dev.yaml"
if [ ! -f "${DEV_SECRET}" ]; then
  echo ""
  echo "[준비 필요] ${DEV_SECRET} 가 없습니다 (공개 저장소 보안상 git 제외됨)."
  if cp k8s/dev/backend-secret-dev.example.yaml "${DEV_SECRET}" 2>/dev/null; then
    echo "  → 템플릿을 복사했습니다. 아래 파일을 열어 <...> 자리표시자에 실제 값을 채우세요:"
  else
    echo "  → 템플릿에서 복사해 실제 값을 채우세요:"
    echo "       cp k8s/dev/backend-secret-dev.example.yaml ${DEV_SECRET}"
  fi
  echo "       vi ${DEV_SECRET}"
  echo "  그 후 다시 실행: ./deploy_eks_dev.sh ${IMAGE_TAG}"
  echo ""
  exit 1
fi

# ─────────────────────────────────────────────
# STEP 1. dev ECR 레포지토리 생성 (이미 있으면 무시)
# ─────────────────────────────────────────────
echo ""
echo "[STEP 1] dev ECR 레포지토리 확인/생성..."
aws ecr create-repository \
  --repository-name mlops-dev/app \
  --region ap-northeast-2 2>/dev/null || echo "  → 레포지토리 이미 존재, 계속 진행"

# ─────────────────────────────────────────────
# STEP 2. Docker 빌드 & dev ECR 푸시
# ─────────────────────────────────────────────
echo ""
echo "[STEP 2] Docker 빌드 & dev ECR 푸시..."
bash build_and_push_dev.sh "${IMAGE_TAG}"

# ─────────────────────────────────────────────
# STEP 3. dev Secret 적용
# ─────────────────────────────────────────────
echo ""
echo "[STEP 3] dev Secret 적용..."
kubectl apply -f k8s/dev/backend-secret-dev.yaml -n mlops

# ─────────────────────────────────────────────
# STEP 4. dev Deployment & Service 적용
# ─────────────────────────────────────────────
echo ""
echo "[STEP 4] dev Deployment & Service 적용..."
kubectl apply -f k8s/dev/backend-deployment-dev.yaml -n mlops
kubectl apply -f k8s/dev/backend-service-dev.yaml -n mlops

# 같은 태그(latest) 재배포 시 이미지 갱신을 강제로 반영
echo "    → 롤아웃 재시작(최신 이미지 pull)..."
kubectl rollout restart deployment/mlops-dev -n mlops

# ─────────────────────────────────────────────
# STEP 5. Pod 기동 대기
# ─────────────────────────────────────────────
echo ""
echo "[STEP 5] Pod 기동 대기 (최대 120초)..."
kubectl rollout status deployment/mlops-dev -n mlops --timeout=120s

# ─────────────────────────────────────────────
# STEP 6. dev Ingress 적용 (dev.mlops.click)
# ─────────────────────────────────────────────
echo ""
echo "[STEP 6] dev Ingress 적용..."
kubectl apply -f k8s/dev/backend-ingress-dev.yaml -n mlops

# ─────────────────────────────────────────────
# STEP 7. 결과 확인
# ─────────────────────────────────────────────
echo ""
echo "[STEP 7] 배포 결과..."
echo "--- Pods (dev) ---"
kubectl get pods -n mlops -l app=mlops-dev
echo ""
echo "--- Service (dev) ---"
kubectl get svc mlops-dev -n mlops
echo ""
echo "--- Ingress (dev) ---"
kubectl get ingress mlops-dev-ingress -n mlops

# ─────────────────────────────────────────────
# STEP 8. 헬스체크 (port-forward)
# ─────────────────────────────────────────────
echo ""
echo "[STEP 8] 헬스체크 (port-forward 6081→6080)..."
pkill -f "kubectl port-forward.*mlops-dev" 2>/dev/null || true
sleep 1
kubectl port-forward svc/mlops-dev 6081:6080 -n mlops >/dev/null 2>&1 &
sleep 3
curl -s http://localhost:6081/health || echo "  (port-forward 헬스체크 실패 — Pod 로그 확인)"
echo ""
pkill -f "kubectl port-forward.*mlops-dev" 2>/dev/null || true

echo ""
echo "======================================================"
echo "  [DEV] 배포 완료!"
echo "  접속: http://dev.mlops.click/"
echo "  (DNS: dev.mlops.click → 운영과 동일한 shared-alb 주소로 CNAME 등록 필요)"
echo "======================================================"
