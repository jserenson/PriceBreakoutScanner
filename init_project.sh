#!/bin/bash

# Initialize git repository
echo "Initializing git..."
git init

# Create virtual environment
echo "Creating virtual environment 'myvenv.nosync' using python3.14..."
python3.14 -m venv myvenv.nosync

# Create .gitignore
echo "Creating .gitignore..."
cat <<EOF > .gitignore
# Git (as requested)
.git

# Virtual Environment
myvenv.nosync/
venv/
.venv/
env/

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
*.db
*.sqbpro


# SQLite temporary and lock files
*.db-journal
*.db-wal
*.db-shm

# Distribution / packaging
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# PyCharm / VSCode
.idea/
.vscode/

# macOS
.DS_Store
EOF

echo "Project initialized successfully."
echo "To activate the virtual environment, run:"
echo "source myvenv.nosync/bin/activate"
echo "Also select the interpreter for your venv"

