# E2E 测试

本项目使用 [Playwright](https://playwright.dev/) 进行端到端测试。

## 运行测试

### 前置条件

确保后端服务已启动：

```bash
cd /opt/dev/qtrader
python -m src.run_manager
```

### 运行所有测试

```bash
npm run test:e2e
```

### 使用 UI 模式运行（推荐开发时使用）

```bash
npm run test:e2e:ui
```

### 调试模式运行

```bash
npm run test:e2e:debug
```

### 运行特定测试文件

```bash
npx playwright test e2e/user-management.spec.ts
```

### 运行特定测试用例

```bash
npx playwright test -g "管理员可以新增用户"
```

## 测试结构

```
e2e/
├── fixtures/           # 测试数据
│   └── users.ts       # 用户测试数据
├── utils/             # 测试工具函数
│   ├── auth.ts        # 登录/登出工具
│   └── user-management.ts  # 用户管理相关工具
├── *.spec.ts          # 测试文件
└── README.md          # 本文档
```

## 用户管理测试覆盖场景

### 功能测试
- ✅ 管理员可以查看用户列表
- ✅ 管理员可以新增用户
- ✅ 管理员可以编辑用户
- ✅ 管理员可以删除用户

### 表单验证
- ✅ 新增用户时用户名必填
- ✅ 新增用户时密码必填
- ✅ 用户名长度验证（3-20字符）
- ✅ 密码长度验证（6-20字符）

### 权限控制
- ✅ trader角色看不到管理菜单
- ✅ guest角色看不到管理菜单
- ✅ 非管理员无法访问系统管理页面

### 边界场景
- ✅ 取消删除用户
- ✅ 编辑用户时可以不修改密码

## 配置

测试配置文件：`playwright.config.ts`

- 基础 URL: `http://localhost:3000`
- 浏览器: Chromium
- 自动启动开发服务器

## 测试数据

测试使用的默认账户：
- duanqing / duanqing123 (管理员)

注意：运行测试前请确保这些账户存在于系统中。
