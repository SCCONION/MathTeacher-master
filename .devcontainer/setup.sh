#!/bin/bash
# Codespaces postCreate 脚本：安装后端 + 前端依赖
set -e

PROJECT=/workspaces/MathTeacher-master

echo "==> 安装 Python 依赖 ..."
cd "$PROJECT"
pip install -r requirements.txt

echo "==> 安装前端依赖 ..."
cd "$PROJECT/web"
npm install

echo "==> 依赖安装完成。"
echo "    启动方式："
echo "      终端1:  cd $PROJECT && uvicorn api.main:app --app-dir src --port 8000"
echo "      终端2:  cd $PROJECT/web && npm run dev -- --host"
echo "    Redis 已通过 devcontainer 自动启动，无需额外操作。"
