/* 登录逻辑 */
const btn = document.getElementById('btn');
const errBox = document.getElementById('err');

btn.onclick = doLogin;
document.getElementById('password').addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });

async function doLogin() {
  const username = document.getElementById('username').value.trim();
  const password = document.getElementById('password').value;
  if (!username || !password) return showErr('请输入用户名和密码');
  btn.disabled = true;
  try {
    const r = await fetch('/api/sys/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    }).then(r => r.json());
    if (r.code !== 0) return showErr(r.msg || '登录失败');   // 统一提示，不泄露账号是否存在
    localStorage.setItem('tcm_token', r.data.token);
    // 按角色分流：普通用户(role=3)进入主页，管理员进入后台
    location.href = (r.data.role === 3) ? '/' : '/admin/';
  } catch (e) {
    showErr('网络错误：' + e.message);
  } finally {
    btn.disabled = false;
  }
}

function showErr(msg) {
  errBox.textContent = msg;
  errBox.classList.remove('d-none');
}
