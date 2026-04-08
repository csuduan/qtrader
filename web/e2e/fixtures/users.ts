/**
 * 测试用户数据
 */
export const testUsers = {
  admin: {
    username: 'duanqing',
    password: 'duanqing123',
    role: 'admin'
  },
  trader: {
    username: 'caizijia',
    password: 'caizijia123',
    role: 'trader'
  },
  guest: {
    username: 'guest',
    password: 'guest123',
    role: 'guest'
  }
}

/**
 * 用于CRUD测试的新用户数据
 */
export const newUserTemplate = {
  username: 'u' + Date.now().toString().slice(-8),
  password: 'testpass123',
  role: 'trader'
}

/**
 * 编辑用户数据
 */
export const editUserTemplate = {
  username: 'editeduser_' + Date.now(),
  role: 'admin'
}
