#!/bin/bash
# Quick deployment script for PHINS Web Portal

echo "🛡️  PHINS Web Portal - Deployment Helper"
echo "========================================"
echo ""
echo "Choose your deployment platform:"
echo ""
echo "1. Railway (Recommended - Free, Easy)"
echo "2. Docker (Self-hosted)"
echo "3. Show deployment instructions"
echo ""
read -p "Enter your choice (1-3): " choice

case $choice in
  1)
    echo ""
    echo "📦 Railway Deployment"
    echo "--------------------"
    echo "1. Go to: https://railway.app"
    echo "2. Sign in with GitHub"
    echo "3. Click 'New Project' → 'Deploy from GitHub repo'"
    echo "4. Select: ashuryasaf/phins"
    echo "5. Railway will auto-detect and deploy!"
    echo ""
    echo "Your site will be live at: https://[project-name].railway.app"
    echo ""
    read -p "Press Enter to open Railway in browser..."
    $BROWSER "https://railway.app/new" 2>/dev/null || echo "Please visit: https://railway.app/new"
    ;;
  3)
    echo ""
    echo "🐳 Docker Deployment"
    echo "-------------------"
    echo "Building Docker image..."
    docker build -t phins-portal .
    
    if [ $? -eq 0 ]; then
      echo ""
      echo "✅ Docker image built successfully!"
      echo ""
      echo "To run locally:"
      echo "  docker run -p 8000:8000 phins-portal"
      echo ""
      echo "To deploy to cloud:"
      echo "  1. Tag: docker tag phins-portal your-registry/phins-portal:latest"
      echo "  2. Push: docker push your-registry/phins-portal:latest"
      echo "  3. Deploy on your platform (AWS ECS, Azure, etc.)"
    else
      echo "❌ Docker build failed. Make sure Docker is running."
    fi
    ;;
  3)
    echo ""
    echo "📖 Opening deployment documentation..."
    cat DEPLOYMENT.md
    ;;
  *)
    echo "Invalid choice. Please run the script again."
    ;;
esac

echo ""
echo "✨ Need help? Check DEPLOYMENT.md for detailed instructions."
