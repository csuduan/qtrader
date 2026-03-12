/**
 * Q-Trader 前端自动化测试脚本
 * 在 Chrome DevTools Console 中直接运行此脚本
 *
 * 使用方法：
 * 1. 打开 http://localhost:3000
 * 2. 按 F12 打开 DevTools
 * 3. 切换到 Console 标签
 * 4. 复制并粘贴此脚本，按回车执行
 */

(function() {
  'use strict';

  // ========== 测试配置 ==========
  const CONFIG = {
    baseUrl: window.location.origin,
    testTimeout: 5000,
    verbose: true
  };

  // ========== 颜色输出 ==========
  const COLORS = {
    reset: '\x1b[0m',
    bright: '\x1b[1m',
    red: '\x1b[31m',
    green: '\x1b[32m',
    yellow: '\x1b[33m',
    blue: '\x1b[34m',
    cyan: '\x1b[36m',
    white: '\x1b[37m'
  };

  // ========== 测试结果统计 ==========
  const results = {
    passed: 0,
    failed: 0,
    skipped: 0,
    tests: []
  };

  // ========== 工具函数 ==========
  function log(message, color = COLORS.white) {
    console.log(`${color}%s${COLORS.reset}`, message);
  }

  function logSuccess(message) {
    log(`✓ ${message}`, COLORS.green);
    results.passed++;
  }

  function logError(message) {
    log(`✗ ${message}`, COLORS.red);
    results.failed++;
  }

  function logWarn(message) {
    log(`⚠ ${message}`, COLORS.yellow);
  }

  function logInfo(message) {
    log(`ℹ ${message}`, COLORS.cyan);
  }

  function logSection(title) {
    console.log(`\n${COLORS.bright}${COLORS.blue}═══ ${title} ═══${COLORS.reset}`);
  }

  // ========== 断言函数 ==========
  function assert(condition, message) {
    if (condition) {
      logSuccess(message);
      return true;
    } else {
      logError(message);
      return false;
    }
  }

  function assertEquals(actual, expected, message) {
    const success = actual === expected;
    const fullMessage = message || `Expected ${expected}, got ${actual}`;
    return assert(success, fullMessage);
  }

  function assertExists(value, message) {
    return assert(value !== null && value !== undefined, message);
  }

  function assertNotNull(value, message) {
    return assert(value !== null, message);
  }

  // ========== 测试类 ==========
  class TestRunner {
    constructor() {
      this.tests = [];
    }

    test(name, fn) {
      this.tests.push({ name, fn });
    }

    async run() {
      logSection('Q-TRADER 前端自动化测试');
      logInfo(`开始时间: ${new Date().toLocaleString()}`);
      logInfo(`测试环境: ${CONFIG.baseUrl}`);

      for (const test of this.tests) {
        try {
          await test.fn();
        } catch (error) {
          logError(`测试异常: ${test.name} - ${error.message}`);
          console.error(error);
        }
      }

      this.printSummary();
    }

    printSummary() {
      logSection('测试结果汇总');
      logInfo(`总计: ${results.passed + results.failed} 项测试`);
      logSuccess(`通过: ${results.passed} 项`);
      if (results.failed > 0) {
        logError(`失败: ${results.failed} 项`);
      }
      if (results.skipped > 0) {
        logWarn(`跳过: ${results.skipped} 项`);
      }

      const passRate = ((results.passed / (results.passed + results.failed)) * 100).toFixed(1);
      logInfo(`通过率: ${passRate}%`);

      // 返回测试结果供外部使用
      return {
        passed: results.passed,
        failed: results.failed,
        passRate: parseFloat(passRate)
      };
    }
  }

  // ========== 测试套件 ==========
  const runner = new TestRunner();

  // ---------- 1. 环境检测测试 ----------
  runner.test('环境检测', () => {
    logSection('1. 环境检测');

    // 检查 Vue 是否加载
    assertExists(window.Vue, 'Vue 框架已加载');

    // 检查 Element Plus 是否加载
    assertExists(window.ElementPlus, 'Element Plus 组件库已加载');

    // 检查路由器
    assertExists(window.$router, 'Vue Router 已实例化');

    // 检查 Pinia store
    assertExists(window.$pinia, 'Pinia 状态管理已初始化');
  });

  // ---------- 2. 全局状态测试 ----------
  runner.test('全局状态检查', async () => {
    logSection('2. 全局状态检查');

    // 等待 store 初始化
    await new Promise(resolve => setTimeout(resolve, 1000));

    // 尝试访问 store（通过 Vue 应用实例）
    const app = document.querySelector('#app')?.__vue_app__;
    assertNotNull(app, 'Vue 应用实例存在');

    if (app) {
      // 检查 Pinia stores
      const stores = app.config.globalProperties.$pinia?.state?.value;
      if (stores) {
        logInfo('已加载的 stores: ' + Object.keys(stores).join(', '));
      }
    }
  });

  // ---------- 3. API 端点测试 ----------
  runner.test('API 端点连通性', async () => {
    logSection('3. API 端点连通性');

    const apiEndpoints = [
      { path: '/api/account', name: '账户信息' },
      { path: '/api/positions', name: '持仓列表' },
      { path: '/api/orders?status=ALIVE', name: '活跃委托' },
      { path: '/api/trades', name: '成交记录' },
      { path: '/api/system/status', name: '系统状态' },
      { path: '/api/alarm/stats', name: '告警统计' },
      { path: '/api/rotation/instructions', name: '换仓指令' }
    ];

    for (const endpoint of apiEndpoints) {
      try {
        const response = await fetch(`${CONFIG.baseUrl}${endpoint.path}`, {
          method: 'GET',
          headers: {
            'Accept': 'application/json'
          }
        });

        const statusOk = response.status >= 200 && response.status < 300;
        const statusMsg = `${endpoint.name} (${endpoint.path})`;

        if (statusOk) {
          logSuccess(`API ${statusMsg} - ${response.status}`);
        } else {
          logError(`API ${statusMsg} - ${response.status}`);
        }

        // 尝试解析响应
        try {
          const data = await response.json();
          if (CONFIG.verbose) {
            logInfo(`  响应数据: ${JSON.stringify(data).substring(0, 100)}...`);
          }
        } catch (e) {
          // 非JSON响应
        }
      } catch (error) {
        logError(`API ${endpoint.name} - 请求失败: ${error.message}`);
      }
    }
  });

  // ---------- 4. WebSocket 连接测试 ----------
  runner.test('WebSocket 连接', () => {
    logSection('4. WebSocket 连接');

    // 检查 WebSocket 连接状态
    // 注意：需要从 Vue 应用实例中获取 wsManager
    const app = document.querySelector('#app')?.__vue_app__;

    if (app && app.config.globalProperties.$wsManager) {
      const ws = app.config.globalProperties.$wsManager;
      assert(ws.connected?.value || ws.connected, 'WebSocket 已连接');
      logInfo(`WebSocket URL: ${ws.url || 'N/A'}`);
    } else {
      logWarn('无法直接访问 wsManager，请手动验证');
      logInfo('请在 Network 标签 > WS 中检查 WebSocket 连接');
    }
  });

  // ---------- 5. 路由测试 ----------
  runner.test('路由配置', () => {
    logSection('5. 路由配置');

    const expectedRoutes = [
      { path: '/dashboard', name: 'Dashboard' },
      { path: '/account', name: 'Account' },
      { path: '/rotation', name: 'Rotation' },
      { path: '/system', name: 'System' },
      { path: '/alarms', name: 'Alarm' }
    ];

    const router = window.$router;
    if (router) {
      const routes = router.getRoutes?.() || router.options?.routes || [];

      logInfo(`已配置路由数: ${routes.length}`);

      for (const expected of expectedRoutes) {
        const found = routes.some(r =>
          r.path === expected.path || r.name === expected.name
        );
        assert(found, `路由 ${expected.path} (${expected.name}) 已配置`);
      }
    } else {
      logWarn('无法访问 router 实例');
    }
  });

  // ---------- 6. DOM 元素检查 ----------
  runner.test('页面 DOM 结构', () => {
    logSection('6. 页面 DOM 结构');

    // 检查关键元素
    const elements = [
      { selector: '#app', name: '根元素 #app' },
      { selector: '.el-container', name: 'Element Plus 容器' },
      { selector: 'nav', name: '导航栏' },
      { selector: '.el-menu', name: '菜单组件' }
    ];

    for (const el of elements) {
      const found = document.querySelector(el.selector);
      assert(found, `DOM 元素 ${el.selector} 存在`);
    }
  });

  // ---------- 7. 组件渲染测试 ----------
  runner.test('当前页面组件渲染', async () => {
    logSection('7. 当前页面组件渲染');

    // 等待组件渲染
    await new Promise(resolve => setTimeout(resolve, 500));

    const currentPath = window.location.pathname;
    logInfo(`当前路径: ${currentPath}`);

    // 根据当前页面检查特定元素
    const pageChecks = {
      '/dashboard': [
        { selector: '.el-statistic', name: '统计卡片' }
      ],
      '/account': [
        { selector: '.el-tabs', name: '标签页' }
      ],
      '/rotation': [
        { selector: '.el-table', name: '指令表格' }
      ],
      '/system': [
        { selector: '.el-descriptions', name: '系统状态描述' }
      ],
      '/alarms': [
        { selector: '.el-table', name: '告警表格' }
      ]
    };

    const checks = pageChecks[currentPath] || [];
    for (const check of checks) {
      const found = document.querySelector(check.selector);
      assert(found, `页面组件 ${check.name} 已渲染`);
    }
  });

  // ---------- 8. 性能检查 ----------
  runner.test('页面性能', () => {
    logSection('8. 页面性能');

    // 获取性能数据
    if (window.performance && window.performance.memory) {
      const memory = window.performance.memory;
      const usedMB = (memory.usedJSHeapSize / 1048576).toFixed(2);
      const totalMB = (memory.totalJSHeapSize / 1048576).toFixed(2);
      const limitMB = (memory.jsHeapSizeLimit / 1048576).toFixed(2);

      logInfo(`内存使用: ${usedMB} MB / ${totalMB} MB (限制: ${limitMB} MB)`);
    }

    // 检查加载时间
    if (window.performance && window.performance.timing) {
      const timing = window.performance.timing;
      const loadTime = timing.loadEventEnd - timing.navigationStart;
      const domReady = timing.domContentLoadedEventEnd - timing.navigationStart;

      logInfo(`页面加载时间: ${loadTime} ms`);
      logInfo(`DOM 就绪时间: ${domReady} ms`);

      assert(loadTime < 5000, `页面加载时间合理 (${loadTime} ms < 5000 ms)`);
    }
  });

  // ---------- 9. Console 错误检查 ----------
  runner.test('Console 错误检测', () => {
    logSection('9. Console 错误检测');

    // 提示用户手动检查
    logInfo('请检查 Console 中是否有红色错误信息');
    logInfo('注意：某些第三方库的警告可以忽略');

    // 检查是否有未捕获的错误
    const originalError = console.error;
    let errorCount = 0;

    console.error = function(...args) {
      errorCount++;
      originalError.apply(console, args);
    };

    setTimeout(() => {
      console.error = originalError;
      if (errorCount === 0) {
        logSuccess('Console 无新错误产生');
      }
    }, 1000);
  });

  // ---------- 10. 本地存储检查 ----------
  runner.test('本地存储', () => {
    logSection('10. 本地存储');

    // 检查 localStorage
    try {
      const lsKeys = Object.keys(localStorage);
      logInfo(`localStorage 键数量: ${lsKeys.length}`);
      if (lsKeys.length > 0) {
        logInfo('localStorage 内容: ' + lsKeys.join(', '));
      }
    } catch (e) {
      logWarn('localStorage 不可用');
    }

    // 检查 sessionStorage
    try {
      const ssKeys = Object.keys(sessionStorage);
      logInfo(`sessionStorage 键数量: ${ssKeys.length}`);
    } catch (e) {
      logWarn('sessionStorage 不可用');
    }
  });

  // ========== 执行测试 ==========
  runner.run().then(summary => {
    // 将结果暴露到全局变量
    window.qtraderTestResults = summary;
    logInfo(`测试完成！结果已保存到 window.qtraderTestResults`);
  });

})();
