#!/bin/bash
set -e

# ==========================================
# [개발용] AWS ECR 빌드 & 푸시
#   운영(build_and_push.sh)과 분리된 dev ECR 사용
# ==========================================
AWS_REGION="ap-northeast-2"
AWS_ACCOUNT_ID="891376975666"
REPO_NAME="mlops-dev/app"            # 개발용 ECR 레포지토리
IMAGE_TAG="${1:-latest}"             # 인자로 태그 지정 가능 (예: ./build_and_push_dev.sh $(git rev-parse --short HEAD))
ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${REPO_NAME}"

echo ">>> [DEV] 1. ECR 로그인..."
aws ecr get-login-password --region ${AWS_REGION} \
  | docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com

echo ">>> [DEV] 2. Docker 이미지 빌드... (tag=${IMAGE_TAG})"
docker build --no-cache -t ${REPO_NAME}:${IMAGE_TAG} .

echo ">>> [DEV] 3. ECR 태그 설정..."
docker tag ${REPO_NAME}:${IMAGE_TAG} ${ECR_URI}:${IMAGE_TAG}

echo ">>> [DEV] 4. ECR 푸시..."
docker push ${ECR_URI}:${IMAGE_TAG}

echo ">>> [DEV] 완료: ${ECR_URI}:${IMAGE_TAG}"
echo "    이제 k8s/dev 매니페스트를 적용하세요 (deploy_eks_dev.sh)."
