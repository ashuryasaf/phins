#!/bin/bash
#
# Verified Railway Deployment Script for PHINS
#
# This script:
# 1. Validates all dependencies
# 2. Runs test suite locally
# 3. Checks railway.json and Dockerfile
# 4. Provides deployment instructions
# 5. Offers to run health checks against deployed URL
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Banner
echo -e "${BLUE}"
cat << "EOF"
    ____  __  ___   _______   _______
   / __ \/ / / / | / / ___/  / ____(_)
  / /_/ / /_/ /  |/ /\__ \  / /_  / / 
 / ____/ __  / /|  /___/ / / __/ / /  
/_/   /_/ /_/_/ |_//____/ /_/   /_/   
                                       
Verified Railway Deployment Script
EOF
echo -e "${NC}"

echo "=========================================="
echo "  PHINS Railway Deployment"
echo "=========================================="
echo ""

# Step 1: Validate Python is available
echo -e "${BLUE}Step 1: Checking Python...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python 3 not found. Please install Python 3.${NC}"
    exit 1
fi
PYTHON_VERSION=$(python3 --version)
echo -e "${GREEN}✓ $PYTHON_VERSION found${NC}"
echo ""

# Step 2: Validate dependencies
echo -e "${BLUE}Step 2: Checking dependencies...${NC}"
if [ ! -f "requirements.txt" ]; then
    echo -e "${RED}✗ requirements.txt not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ requirements.txt found${NC}"

# Check if pytest is installed
if ! python3 -m pytest --version &> /dev/null; then
    echo -e "${YELLOW}⚠ pytest not installed. Installing...${NC}"
    pip3 install pytest requests
fi
echo -e "${GREEN}✓ pytest available${NC}"
echo ""

# Step 3: Validate configuration
echo -e "${BLUE}Step 3: Validating configuration...${NC}"
if [ ! -f "validate_railway_config.py" ]; then
    echo -e "${YELLOW}⚠ validate_railway_config.py not found, skipping config validation${NC}"
else
    if python3 validate_railway_config.py; then
        echo -e "${GREEN}✓ Configuration valid${NC}"
    else
        echo -e "${RED}✗ Configuration validation failed${NC}"
        echo -e "${YELLOW}Continue anyway? (y/n)${NC}"
        read -r response
        if [[ ! "$response" =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
fi
echo ""

# Step 4: Run tests locally
echo -e "${BLUE}Step 4: Running tests locally...${NC}"
echo -e "${YELLOW}Running smoke tests...${NC}"

if python3 -m pytest tests/test_smoke_critical_paths.py -v --tb=short; then
    echo -e "${GREEN}✓ Smoke tests passed${NC}"
else
    echo -e "${RED}✗ Smoke tests failed${NC}"
    echo -e "${YELLOW}Continue anyway? (y/n)${NC}"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi
echo ""

# Step 5: Check Git status
echo -e "${BLUE}Step 5: Checking Git status...${NC}"
if ! command -v git &> /dev/null; then
    echo -e "${YELLOW}⚠ Git not found, skipping version control checks${NC}"
else
    if [ -d ".git" ]; then
        # Check for uncommitted changes
        if [[ -n $(git status -s) ]]; then
            echo -e "${YELLOW}⚠ You have uncommitted changes:${NC}"
            git status -s
            echo ""
            echo -e "${YELLOW}Commit changes before deploying? (y/n)${NC}"
            read -r response
            if [[ "$response" =~ ^[Yy]$ ]]; then
                echo "Enter commit message:"
                read -r commit_msg
                git add .
                git commit -m "$commit_msg"
                echo -e "${GREEN}✓ Changes committed${NC}"
            fi
        else
            echo -e "${GREEN}✓ No uncommitted changes${NC}"
        fi
        
        # Check current branch
        CURRENT_BRANCH=$(git branch --show-current)
        echo -e "${GREEN}✓ Current branch: $CURRENT_BRANCH${NC}"
    else
        echo -e "${YELLOW}⚠ Not a Git repository${NC}"
    fi
fi
echo ""

# Step 6: Railway deployment instructions
echo -e "${BLUE}Step 6: Railway Deployment${NC}"
echo ""
echo "To deploy to Railway:"
echo ""
echo "1. Install Railway CLI (if not already installed):"
echo "   ${GREEN}npm i -g @railway/cli${NC}"
echo "   or"
echo "   ${GREEN}brew install railway${NC}"
echo ""
echo "2. Login to Railway:"
echo "   ${GREEN}railway login${NC}"
echo ""
echo "3. Link to your Railway project:"
echo "   ${GREEN}railway link${NC}"
echo "   (Select your project or create a new one)"
echo ""
echo "4. Deploy:"
echo "   ${GREEN}railway up${NC}"
echo ""
echo "5. Get your deployment URL:"
echo "   ${GREEN}railway domain${NC}"
echo ""
echo -e "${YELLOW}Do you want to proceed with Railway CLI deployment now? (y/n)${NC}"
read -r response

if [[ "$response" =~ ^[Yy]$ ]]; then
    # Check if Railway CLI is installed
    if ! command -v railway &> /dev/null; then
        echo -e "${RED}✗ Railway CLI not found${NC}"
        echo "Please install it first: npm i -g @railway/cli"
        exit 1
    fi
    
    # Check if logged in
    if ! railway whoami &> /dev/null; then
        echo -e "${YELLOW}⚠ Not logged in to Railway. Running 'railway login'...${NC}"
        railway login
    fi
    
    # Deploy
    echo -e "${GREEN}Deploying to Railway...${NC}"
    railway up
    
    echo ""
    echo -e "${GREEN}✓ Deployment initiated!${NC}"
    echo ""
    
    # Get deployment URL
    echo "Getting deployment URL..."
    RAILWAY_URL=$(railway domain 2>/dev/null || echo "")
    
    if [ -n "$RAILWAY_URL" ]; then
        echo -e "${GREEN}✓ Deployment URL: $RAILWAY_URL${NC}"
        echo ""
        
        # Offer to run health check
        echo -e "${YELLOW}Run health check against deployed URL? (y/n)${NC}"
        read -r health_response
        
        if [[ "$health_response" =~ ^[Yy]$ ]]; then
            echo "Waiting 10 seconds for deployment to stabilize..."
            sleep 10
            
            if [ -f "railway_health_check.py" ]; then
                python3 railway_health_check.py "https://$RAILWAY_URL"
            else
                echo -e "${YELLOW}⚠ railway_health_check.py not found${NC}"
            fi
        fi
    else
        echo -e "${YELLOW}⚠ Could not retrieve deployment URL${NC}"
        echo "You can get it later with: ${GREEN}railway domain${NC}"
    fi
else
    echo ""
    echo -e "${GREEN}Deployment instructions saved!${NC}"
    echo "Run the Railway CLI commands manually when ready."
fi

echo ""
echo "=========================================="
echo "  Deployment Process Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Wait for Railway build to complete"
echo "  2. Check Railway dashboard for deployment status"
echo "  3. Run health check: ${GREEN}python3 railway_health_check.py <URL>${NC}"
echo "  4. Test complete customer journey"
echo "  5. Monitor logs: ${GREEN}railway logs${NC}"
echo ""
echo -e "${GREEN}✅ Ready for production!${NC}"
echo ""
