#!/bin/bash
# ============================================================
# MLFoundry EKS 전체 배포 스크립트
# AWS Account : 891376975666
# Region      : ap-northeast-2
# Namespace   : mlops
# ECR         : mlops/app
# ============================================================
set -e

echo ""
echo "======================================================"
echo "  MLFoundry EKS 배포 시작"
echo "======================================================"

# ─────────────────────────────────────────────
# STEP 0. 사전 점검 — Secret 파일 존재 확인
#   실제 값이 담긴 Secret 은 보안상 git 제외(.gitignore)됨.
# ─────────────────────────────────────────────
PROD_SECRET="k8s/backend-secret.yaml"
if [ ! -f "${PROD_SECRET}" ]; then
  echo ""
  echo "[준비 필요] ${PROD_SECRET} 가 없습니다 (공개 저장소 보안상 git 제외됨)."
  if cp k8s/backend-secret.example.yaml "${PROD_SECRET}" 2>/dev/null; then
    echo "  → 템플릿을 복사했습니다. 아래 파일을 열어 <...> 자리표시자에 실제 값을 채우세요:"
  else
    echo "  → 템플릿에서 복사해 실제 값을 채우세요:"
    echo "       cp k8s/backend-secret.example.yaml ${PROD_SECRET}"
  fi
  echo "       vi ${PROD_SECRET}"
  echo "  그 후 다시 실행: ./deploy_eks.sh"
  echo ""
  exit 1
fi

# ─────────────────────────────────────────────
# STEP 1. ECR 레포지토리 생성 (이미 있으면 무시)
# ─────────────────────────────────────────────
echo ""
echo "[STEP 1] ECR 레포지토리 확인/생성..."
aws ecr create-repository \
  --repository-name mlops/app \
  --region ap-northeast-2 2>/dev/null || echo "  → 레포지토리 이미 존재, 계속 진행"

# ─────────────────────────────────────────────
# STEP 2. Docker 이미지 빌드 & ECR 푸시
# ─────────────────────────────────────────────
echo ""
echo "[STEP 2] Docker 이미지 빌드 & ECR 푸시..."
bash build_and_push.sh

# ─────────────────────────────────────────────
# STEP 3. K8s Secret 적용
# ─────────────────────────────────────────────
echo ""
echo "[STEP 3] Secret 적용..."
kubectl apply -f k8s/backend-secret.yaml -n mlops

# ─────────────────────────────────────────────
# STEP 4. Deployment & Service 적용
# ─────────────────────────────────────────────
echo ""
echo "[STEP 4] Deployment & Service 적용..."
kubectl apply -f k8s/backend-deployment.yaml -n mlops
kubectl apply -f k8s/backend-service.yaml -n mlops

# ─────────────────────────────────────────────
# STEP 5. Pod 기동 대기
# ─────────────────────────────────────────────
echo ""
echo "[STEP 5] Pod 기동 대기 (최대 60초)..."
# DEPLOY_NAME=$(kubectl get deployment -n mlops -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "ml")
kubectl rollout status deployment/mlops -n mlops --timeout=60s

# ─────────────────────────────────────────────
# STEP 6. Ingress (ALB) 적용
# ─────────────────────────────────────────────
echo ""
echo "[STEP 6] Ingress(ALB) 적용..."
#kubectl apply -f k8s/backend-ingress.yaml -n mlops

# ─────────────────────────────────────────────
# STEP 7. 배포 결과 확인
# ─────────────────────────────────────────────
echo ""
echo "[STEP 7] 배포 결과 확인..."
echo ""
echo "--- Pods ---"
kubectl get pods -n mlops

echo ""
echo "--- Services ---"
kubectl get svc -n mlops

echo ""
echo "--- Ingress (ALB 주소 발급까지 1~3분 소요) ---"
kubectl get ingress -n mlops

# ─────────────────────────────────────────────
# STEP 8. 헬스체크
# ─────────────────────────────────────────────
echo ""
echo "[STEP 8] 헬스체크 (port-forward)..."
pkill -f "kubectl port-forward" 2>/dev/null; sleep 1
SVC_NAME=$(kubectl get svc -n mlops -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "mlfoundry-backend")
kubectl port-forward svc/$SVC_NAME 6080:6080 -n mlops &
sleep 2
curl -s http://localhost:6080/health
echo ""

echo ""
echo "======================================================"
echo "  배포 완료!"
echo "======================================================"
echo ""
echo "  ALB 주소 확인 (1~3분 후):"
echo "  kubectl get ingress mlops-ingress -n mlops"
echo ""
echo "  ALB로 헬스체크:"
echo '  ALB_HOST=$(kubectl get ingress mlfoundry-ingress -n mlops -o jsonpath='\''{.status.loadBalancer.ingress[0].hostname}'\'')'
echo "  curl http://\$ALB_HOST/health"
echo ""
