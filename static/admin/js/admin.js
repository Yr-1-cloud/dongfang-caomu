/* 后台管理逻辑：模块切换 + 12 个功能模块 + 通用弹窗/分页。 */

const TOKEN = localStorage.getItem('tcm_token') || '';
const $ = sel => document.querySelector(sel);

/* ---------------- 基础工具 ---------------- */
async function api(url, method = 'GET', body) {
  const r = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-Token': TOKEN },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (r.status === 401) { location.href = 'login.html'; throw new Error('未登录'); }
  return r.json();
}

async function uploadApi(url, formData) {
  const r = await fetch(url, { method: 'POST', headers: { 'X-Token': TOKEN }, body: formData });
  if (r.status === 401) { location.href = 'login.html'; throw new Error('未登录'); }
  return r.json();
}

async function downloadCsv(url, filename) {
  const r = await fetch(url, { headers: { 'X-Token': TOKEN } });
  if (r.status === 401) { location.href = 'login.html'; return; }
  const blob = await r.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

function esc(s) {
  return (s ?? '').toString().replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

const REVIEW = { 0: ['待复核', 'warning'], 1: ['已复核', 'success'], 2: ['已拒绝', 'danger'] };
const VECTOR = { 0: ['未入库', 'secondary'], 1: ['已入库', 'success'] };
const SOURCE = { fangji: '方剂', zhongyao: '中药材', pianfang: '偏方', doc: '上传文档', manual: '手工录入' };
const bdg = (map, v) => `<span class="badge badge-sm bg-${(map[v] || ['', 'secondary'])[1]}">${(map[v] || ['未知'])[0]}</span>`;
const fmtSize = n => n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : (n / 1024).toFixed(0) + ' KB';

let dlgModal = null;
function dlg(title, bodyHtml, onOk) {
  $('#dlgTitle').textContent = title;
  $('#dlgBody').innerHTML = bodyHtml;
  const okBtn = $('#dlgOk');
  okBtn.onclick = async () => {
    try {
      const close = await onOk($('#dlgBody'));
      if (close !== false) dlgModal.hide();
    } catch (e) { alert(e.message || e); }
  };
  dlgModal.show();
}

function confirmBox(msg, onOk) {
  dlg('请确认', `<p class="mb-0">${esc(msg)}</p>`, async () => { await onOk(); });
}

function pager(el, total, page, size, go) {
  const pages = Math.max(1, Math.ceil(total / size));
  el.innerHTML = `
    <span class="small text-muted me-2">共 ${total} 条 / ${pages} 页</span>
    <button class="btn btn-sm btn-outline-secondary" ${page <= 1 ? 'disabled' : ''} data-p="${page - 1}">上一页</button>
    <span class="mx-2 small">${page} / ${pages}</span>
    <button class="btn btn-sm btn-outline-secondary" ${page >= pages ? 'disabled' : ''} data-p="${page + 1}">下一页</button>`;
  el.querySelectorAll('button[data-p]').forEach(b => b.onclick = () => go(+b.dataset.p));
}

/* ---------------- 模块注册与侧边栏 ---------------- */
const SECTIONS = {
  kb:       { label: '结构化数据', render: renderKb },
  doc:      { label: '文档管理',   render: renderDoc },
  qalog:    { label: '问答日志',   render: renderQaLog },
  user:     { label: '用户管理',   render: renderUser },
  role:     { label: '角色管理',   render: renderRole },
  dept:     { label: '部门管理',   render: renderDept },
  menu:     { label: '菜单管理',   render: renderMenu },
  dict:     { label: '字典管理',   render: renderDict },
  attach:   { label: '附件管理',   render: renderAttach },
  config:   { label: '参数配置',   render: renderConfig },
  loginlog: { label: '登录日志',   render: renderLoginLog },
  operlog:  { label: '操作日志',   render: renderOperLog },
};
const PERM2SEC = {
  'kb:data': 'kb', 'kb:doc': 'doc', 'qa:log': 'qalog', 'sys:user': 'user', 'sys:role': 'role',
  'sys:dept': 'dept', 'sys:menu': 'menu', 'sys:dict': 'dict', 'sys:attach': 'attach',
  'sys:config': 'config', 'sys:loginlog': 'loginlog', 'sys:operlog': 'operlog',
};

let current = '';
async function init() {
  dlgModal = new bootstrap.Modal('#dlg');
  $('#btnLogout').onclick = async () => {
    await api('/api/sys/logout', 'POST', {});
    localStorage.removeItem('tcm_token');
    location.href = 'login.html';
  };
  const me = await api('/api/sys/me');
  // 普通用户(role=3)无后台权限，直接退回主页
  if (me.data.role === 3) { location.href = '/'; return; }
  $('#who').textContent = me.data.username;
  const sidebar = $('#sidebar');
  const items = me.data.menus;
  const link = m => {
    const sec = PERM2SEC[m.perm];
    return sec ? `<a class="nav-link" data-sec="${sec}" href="#">${esc(m.name)}</a>` : '';
  };
  // 两级菜单：type=目录 的作为分组标题，子菜单挂其下；没归组的兜底平铺
  const grouped = new Set();
  let html = `<div class="menu-group">功能菜单</div>`;
  items.filter(m => m.type === '目录').forEach(d => {
    const kids = items.filter(m => m.parent_id === d.id && m.type !== '目录');
    if (!kids.length) return;
    kids.forEach(k => grouped.add(k.id));
    html += `<div class="menu-dir" data-dir="${d.id}"><span>${esc(d.name)}</span><span class="caret">▾</span></div>` +
            `<div class="menu-sub">${kids.map(link).join('')}</div>`;
  });
  html += items.filter(m => m.type !== '目录' && !grouped.has(m.id)).map(link).join('');
  sidebar.innerHTML = html;
  sidebar.querySelectorAll('.nav-link').forEach(a => a.onclick = e => { e.preventDefault(); switchSec(a.dataset.sec); });
  sidebar.querySelectorAll('.menu-dir').forEach(h => h.onclick = () => {
    h.classList.toggle('closed');
    h.nextElementSibling.classList.toggle('closed');
  });
  const first = Object.keys(SECTIONS).find(k => sidebar.querySelector(`[data-sec="${k}"]`));
  if (first) switchSec(first);
}

function switchSec(sec) {
  current = sec;
  document.querySelectorAll('.sec').forEach(d => d.classList.add('d-none'));
  document.querySelectorAll('#sidebar .nav-link').forEach(a => a.classList.toggle('active', a.dataset.sec === sec));
  const el = $('#sec-' + sec);
  el.classList.remove('d-none');
  SECTIONS[sec].render(el);
}

/* ================= 结构化数据（知识管理） ================= */
function renderKb(el) {
  let page = 1;
  el.innerHTML = `
    <div class="row g-3 mb-3" id="kb-cards"></div>
    <div class="progress mb-1" style="height:6px"><div id="kb-bar" class="progress-bar bg-success"></div></div>
    <div class="small text-muted mb-2" id="kb-prog"></div>
    <div class="d-flex flex-wrap gap-2 mb-2 align-items-center">
      <select id="kb-source" class="form-select form-select-sm w-auto">
        <option value="">全部来源</option>
        ${Object.entries(SOURCE).map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}
      </select>
      <select id="kb-review" class="form-select form-select-sm w-auto">
        <option value="">复核状态</option><option value="0">待复核</option><option value="1">已复核</option><option value="2">已拒绝</option>
      </select>
      <select id="kb-vector" class="form-select form-select-sm w-auto">
        <option value="">向量状态</option><option value="0">未入库</option><option value="1">已入库</option>
      </select>
      <input id="kb-kw" class="form-control form-control-sm w-auto" placeholder="标题关键词">
      <button id="kb-search" class="btn btn-sm btn-success">查询</button>
      <button id="kb-add" class="btn btn-sm btn-outline-success">＋ 手工录入</button>
    </div>
    <div class="table-responsive"><table class="table table-sm table-hover align-middle">
      <thead class="table-light"><tr><th>ID</th><th>标题</th><th>来源</th><th>复核</th><th>向量</th><th style="width:270px">操作</th></tr></thead>
      <tbody id="kb-rows"></tbody></table></div>
    <div id="kb-page"></div>`;

  const load = async () => {
    const [st, ls] = await Promise.all([
      api('/api/admin/stats'),
      api(`/api/admin/list?page=${page}&size=15&source=${$('#kb-source').value}&review_status=${$('#kb-review').value}&vector_status=${$('#kb-vector').value}&keyword=${encodeURIComponent($('#kb-kw').value)}`),
    ]);
    const d = st.data;
    $('#kb-cards').innerHTML = [
      ['知识总量', d.total, 'primary'], ['已进向量库', d.vectorized, 'success'],
      ['待复核', d.pending_review, 'warning'],
    ].map(([t, v, c]) => `<div class="col-md-3 col-6"><div class="card card-stat shadow-sm"><div class="card-body py-3">
        <div class="small text-muted">${t}</div><div class="fs-4 fw-bold text-${c}">${v}</div></div></div></div>`).join('');
    const pct = d.total ? (d.vectorized / d.total * 100) : 0;
    $('#kb-bar').style.width = pct.toFixed(1) + '%';
    $('#kb-prog').textContent = `全量向量化进度：${d.vectorized} / ${d.total}（${pct.toFixed(1)}%，后台任务持续推进中）`;
    $('#kb-rows').innerHTML = ls.data.rows.map(r => `<tr>
      <td>${r.id}</td><td class="text-truncate" style="max-width:260px" title="${esc(r.title)}">${esc(r.title)}</td>
      <td>${SOURCE[r.source] || r.source}</td>
      <td>${bdg(REVIEW, r.review_status)}</td><td>${bdg(VECTOR, r.vector_status)}</td>
      <td>
        <button class="btn btn-sm btn-outline-success me-1" data-act="pass" data-id="${r.id}">通过</button>
        <button class="btn btn-sm btn-outline-danger me-1" data-act="reject" data-id="${r.id}">拒绝</button>
        <button class="btn btn-sm btn-outline-primary me-1" data-act="edit" data-id="${r.id}">编辑</button>
        <button class="btn btn-sm btn-outline-danger" data-act="del" data-id="${r.id}">删除</button>
      </td></tr>`).join('') || '<tr><td colspan="6" class="text-center text-muted py-4">无数据</td></tr>';
    pager($('#kb-page'), ls.data.total, page, 15, p => { page = p; load(); });

    $('#kb-rows').querySelectorAll('button[data-act]').forEach(b => b.onclick = () => rowAct(b.dataset.act, +b.dataset.id, load));
  };
  $('#kb-search').onclick = () => { page = 1; load(); };
  $('#kb-add').onclick = () => dlg('手工录入', `
      <div class="mb-2"><label class="form-label">标题</label><input id="f-title" class="form-control"></div>
      <div><label class="form-label">内容</label><textarea id="f-content" class="form-control" rows="8"></textarea></div>`,
    async () => {
      const r = await api('/api/admin/add', 'POST', { title: $('#f-title').value.trim(), content: $('#f-content').value });
      if (r.code !== 0) throw new Error(r.msg);
      load();
    });
  load();
}

async function rowAct(act, id, reload) {
  if (act === 'edit') {
    const d = await api('/api/admin/detail?id=' + id);
    if (d.code !== 0) return alert(d.msg);
    return dlg('编辑知识 #' + id, `
      <div class="mb-2"><label class="form-label">标题</label><input id="f-title" class="form-control" value="${esc(d.data.title)}"></div>
      <div><label class="form-label">内容（保存后自动同步向量库）</label><textarea id="f-content" class="form-control" rows="10">${esc(d.data.content)}</textarea></div>`,
      async () => {
        const r = await api('/api/admin/edit', 'POST', { id, title: $('#f-title').value.trim(), content: $('#f-content').value });
        if (r.code !== 0) throw new Error(r.msg);
        reload();
      });
  }
  if (act === 'del') return confirmBox(`确定删除知识 #${id}？将同步撤下向量。`, async () => {
    const r = await api('/api/admin/delete', 'POST', { id });
    if (r.code !== 0) throw new Error(r.msg);
    reload();
  });
  const r = await api('/api/admin/review', 'POST', { id, action: act });
  if (r.code !== 0) return alert(r.msg);
  reload();
}

/* ================= 文档管理 ================= */
function renderDoc(el) {
  let page = 1;
  el.innerHTML = `
    <div class="d-flex flex-wrap gap-2 mb-2 align-items-center">
      <input type="file" id="doc-file" class="form-control form-control-sm w-auto" accept=".pdf,.txt,.md">
      <button id="doc-up" class="btn btn-sm btn-success">上传（MD5 去重秒传）</button>
      <span class="small text-muted">上传后自动：解析 → 抽取 → 转入"待复核"，在【结构化数据】里复核。</span>
    </div>
    <div class="d-flex flex-wrap gap-2 mb-2">
      <input id="doc-kw" class="form-control form-control-sm w-auto" placeholder="文件名关键词">
      <button id="doc-search" class="btn btn-sm btn-success">查询</button>
    </div>
    <div class="table-responsive"><table class="table table-sm table-hover align-middle">
      <thead class="table-light"><tr><th>ID</th><th>文件名</th><th>大小</th><th>来源模块</th><th>解析状态</th><th>上传时间</th><th>操作</th></tr></thead>
      <tbody id="doc-rows"></tbody></table></div>
    <div id="doc-page"></div>`;

  const load = async () => {
    const r = await api(`/api/sys/attach/list?page=${page}&size=15&module=doc&keyword=${encodeURIComponent($('#doc-kw').value)}`);
    $('#doc-rows').innerHTML = r.data.rows.map(a => `<tr>
      <td>${a.id}</td><td>${esc(a.file_name)}</td><td>${fmtSize(a.file_size)}</td>
      <td>${esc(a.source_module || '-')}</td>
      <td>${a.kid ? bdg(REVIEW, a.review_status) + ' ' + bdg(VECTOR, a.vector_status) : '<span class="text-muted">未关联</span>'}</td>
      <td class="small">${esc((a.created_at || '').slice(0, 19))}</td>
      <td><button class="btn btn-sm btn-outline-primary" data-id="${a.id}">预览</button></td></tr>`).join('')
      || '<tr><td colspan="7" class="text-center text-muted py-4">暂无文档</td></tr>';
    $('#doc-rows').querySelectorAll('button').forEach(b => b.onclick = () =>
      window.open('/api/sys/attach/download?id=' + b.dataset.id + '&token=' + encodeURIComponent(TOKEN)));
    pager($('#doc-page'), r.data.total, page, 15, p => { page = p; load(); });
  };
  $('#doc-search').onclick = () => { page = 1; load(); };
  $('#doc-up').onclick = async () => {
    const f = $('#doc-file').files[0];
    if (!f) return alert('请先选择文件');
    const fd = new FormData();
    fd.append('file', f);
    const r = await uploadApi('/api/admin/upload', fd);
    alert(r.msg);
    load();
  };
  load();
}

/* ================= 问答日志 ================= */
function renderQaLog(el) {
  el.innerHTML = `
    <div class="table-responsive"><table class="table table-sm table-hover align-middle bg-white">
      <thead class="table-light"><tr><th>ID</th><th>问题</th><th>命中条数</th><th>来源分布</th><th>最高相似度</th><th>耗时(ms)</th><th>是否命中</th><th>时间</th></tr></thead>
      <tbody id="qa-rows"></tbody></table></div>`;
  api('/api/qa/logs?limit=100').then(rows => {
    rows = Array.isArray(rows) ? rows : [];
    $('#qa-rows').innerHTML = rows.map(r => `<tr>
      <td>${r.id}</td><td class="text-truncate" style="max-width:280px" title="${esc(r.question)}">${esc(r.question)}</td>
      <td>${r.hit_count}</td><td>${esc(r.sources || '-')}</td>
      <td>${(r.top_score * 100).toFixed(0)}%</td><td>${r.elapsed_ms}</td>
      <td>${r.hit_count > 0 && r.top_score >= 0.5 ? '<span class="badge bg-success badge-sm">命中</span>' : '<span class="badge bg-secondary badge-sm">拒答</span>'}</td>
      <td class="small">${esc((r.created_at || '').slice(0, 19))}</td></tr>`).join('')
      || '<tr><td colspan="8" class="text-center text-muted py-4">暂无问答记录</td></tr>';
  });
}

/* ================= 用户管理 ================= */
function renderUser(el) {
  let page = 1;
  el.innerHTML = `
    <div class="d-flex gap-2 mb-2">
      <input id="u-kw" class="form-control form-control-sm w-auto" placeholder="用户名/昵称/手机">
      <button id="u-search" class="btn btn-sm btn-success">查询</button>
      <button id="u-add" class="btn btn-sm btn-outline-success">＋ 新增</button>
      <button id="u-export" class="btn btn-sm btn-outline-secondary">导出</button>
    </div>
    <div class="table-responsive"><table class="table table-sm table-hover align-middle bg-white">
      <thead class="table-light"><tr><th>ID</th><th>用户名</th><th>昵称</th><th>手机</th><th>部门</th><th>角色</th><th>状态</th><th>创建时间</th><th style="width:270px">操作</th></tr></thead>
      <tbody id="u-rows"></tbody></table></div>
    <div id="u-page"></div>`;

  const load = async () => {
    const [us, roles, depts] = await Promise.all([
      api(`/api/sys/user/list?page=${page}&size=15&keyword=${encodeURIComponent($('#u-kw').value)}`),
      api('/api/sys/role/list'),
      api('/api/sys/dept/tree'),
    ]);
    const roleOpts = id => roles.data.map(r => `<option value="${r.id}" ${r.id === id ? 'selected' : ''}>${esc(r.name)}</option>`).join('');
    const deptOpts = (id, list, depth = 0) => list.map(d =>
      `<option value="${d.id}" ${d.id === id ? 'selected' : ''}>${'　'.repeat(depth)}${esc(d.name)}</option>` +
      deptOpts(id, d.children || [], depth + 1)).join('');
    $('#u-rows').innerHTML = us.data.rows.map(u => `<tr>
      <td>${u.id}</td><td>${esc(u.username)}</td><td>${esc(u.nickname || '-')}</td><td>${esc(u.phone || '-')}</td>
      <td>${esc(u.dept_name || '-')}</td><td>${esc(u.role_name || '-')}</td>
      <td>${u.status === 1 ? '<span class="badge bg-success badge-sm">启用</span>' : '<span class="badge bg-secondary badge-sm">停用</span>'}</td>
      <td class="small">${esc((u.created_at || '').slice(0, 19))}</td>
      <td>
        <button class="btn btn-sm btn-outline-primary me-1" data-act="edit" data-u='${esc(JSON.stringify(u))}'>编辑</button>
        <button class="btn btn-sm btn-outline-warning me-1" data-act="pwd" data-id="${u.id}">重置密码</button>
        <button class="btn btn-sm btn-outline-secondary me-1" data-act="toggle" data-id="${u.id}" data-s="${u.status}">${u.status === 1 ? '停用' : '启用'}</button>
        <button class="btn btn-sm btn-outline-danger" data-act="del" data-id="${u.id}">删除</button>
      </td></tr>`).join('');
    pager($('#u-page'), us.data.total, page, 15, p => { page = p; load(); });

    $('#u-rows').querySelectorAll('button').forEach(b => b.onclick = async () => {
      const act = b.dataset.act, id = +b.dataset.id;
      if (act === 'edit') {
        const u = JSON.parse(b.dataset.u);
        return dlg('编辑用户', `
          <div class="mb-2">用户名：<b>${esc(u.username)}</b></div>
          <div class="mb-2"><label class="form-label">昵称</label><input id="f-nick" class="form-control" value="${esc(u.nickname || '')}"></div>
          <div class="mb-2"><label class="form-label">手机</label><input id="f-phone" class="form-control" value="${esc(u.phone || '')}"></div>
          <div class="mb-2"><label class="form-label">部门</label><select id="f-dept" class="form-select">${deptOpts(u.dept_id, depts.data)}</select></div>
          <div class="mb-2"><label class="form-label">角色</label><select id="f-role" class="form-select">${roleOpts(u.role_id)}</select></div>`,
          async () => {
            const r = await api('/api/sys/user/save', 'POST', {
              id, nickname: $('#f-nick').value, phone: $('#f-phone').value,
              dept_id: +$('#f-dept').value, role_id: +$('#f-role').value,
            });
            if (r.code !== 0) throw new Error(r.msg);
            load();
          });
      }
      if (act === 'pwd') {
        return dlg('重置密码（用户 #' + id + '）',
          `<div><label class="form-label">新密码</label><input id="f-pwd" class="form-control" value="123456"></div>`,
          async () => {
            const r = await api('/api/sys/user/resetPwd', 'POST', { id, password: $('#f-pwd').value });
            if (r.code !== 0) throw new Error(r.msg);
            alert(r.data || r.msg);
          });
      }
      if (act === 'toggle') {
        const r = await api('/api/sys/user/status', 'POST', { id, status: +b.dataset.s === 1 ? 0 : 1 });
        if (r.code !== 0) return alert(r.msg);
        load();
      }
      if (act === 'del') return confirmBox('确定删除该用户？', async () => {
        const r = await api('/api/sys/user/delete', 'POST', { id });
        if (r.code !== 0) throw new Error(r.msg);
        load();
      });
    });
  };
  $('#u-search').onclick = () => { page = 1; load(); };
  $('#u-add').onclick = () => dlg('新增用户', `
      <div class="mb-2"><label class="form-label">用户名</label><input id="f-username" class="form-control"></div>
      <div class="mb-2"><label class="form-label">昵称</label><input id="f-nick" class="form-control"></div>
      <div class="mb-2"><label class="form-label">手机</label><input id="f-phone" class="form-control"></div>
      <div class="mb-2"><label class="form-label">初始密码</label><input id="f-pwd" class="form-control" value="123456"></div>
      <div class="mb-2"><label class="form-label">部门 / 角色</label><div class="d-flex gap-2">
        <select id="f-dept" class="form-select"></select><select id="f-role" class="form-select"></select></div></div>`,
    async body => {
      const r = await api('/api/sys/user/save', 'POST', {
        username: $('#f-username').value.trim(), nickname: $('#f-nick').value, phone: $('#f-phone').value,
        password: $('#f-pwd').value, dept_id: +$('#f-dept').value, role_id: +$('#f-role').value,
      });
      if (r.code !== 0) throw new Error(r.msg);
      alert(r.data || r.msg);
      load();
    });
  // 弹窗打开后填充部门/角色下拉（新增时 dlgBody 已就绪，延后一拍）
  const patchAddDlg = new MutationObserver(() => {
    const sel = $('#f-dept');
    if (sel && !sel.options.length) {
      api('/api/sys/role/list').then(r => $('#f-role').innerHTML = r.data.map(x => `<option value="${x.id}">${esc(x.name)}</option>`).join(''));
      api('/api/sys/dept/tree').then(r => {
        const flat = (list, d = 0) => list.map(x => `<option value="${x.id}">${'　'.repeat(d)}${esc(x.name)}</option>` + flat(x.children || [], d + 1)).join('');
        sel.innerHTML = flat(r.data);
      });
    }
  });
  patchAddDlg.observe($('#dlgBody'), { childList: true });
  $('#u-export').onclick = () => downloadCsv('/api/sys/user/export', 'users.csv');
  load();
}

/* ================= 角色管理 ================= */
function renderRole(el) {
  el.innerHTML = `
    <div class="mb-2"><button id="r-add" class="btn btn-sm btn-outline-success">＋ 新增角色</button></div>
    <table class="table table-sm table-hover align-middle bg-white">
      <thead class="table-light"><tr><th>ID</th><th>角色名</th><th>备注</th><th>状态</th><th style="width:250px">操作</th></tr></thead>
      <tbody id="r-rows"></tbody></table>`;

  const load = async () => {
    const r = await api('/api/sys/role/list');
    $('#r-rows').innerHTML = r.data.map(x => `<tr>
      <td>${x.id}</td><td>${esc(x.name)}</td><td>${esc(x.remark || '-')}</td>
      <td>${x.status === 1 ? '<span class="badge bg-success badge-sm">启用</span>' : '<span class="badge bg-secondary badge-sm">停用</span>'}</td>
      <td>
        <button class="btn btn-sm btn-outline-primary me-1" data-act="edit" data-x='${esc(JSON.stringify(x))}'>编辑</button>
        <button class="btn btn-sm btn-outline-success me-1" data-act="perm" data-id="${x.id}" data-name="${esc(x.name)}">分配权限</button>
        <button class="btn btn-sm btn-outline-danger" data-act="del" data-id="${x.id}">删除</button>
      </td></tr>`).join('');
    $('#r-rows').querySelectorAll('button').forEach(b => b.onclick = async () => {
      const act = b.dataset.act, id = +b.dataset.id;
      if (act === 'edit') {
        const x = JSON.parse(b.dataset.x);
        return dlg('编辑角色', `
          <div class="mb-2"><label class="form-label">角色名</label><input id="f-name" class="form-control" value="${esc(x.name)}"></div>
          <div><label class="form-label">备注</label><input id="f-remark" class="form-control" value="${esc(x.remark || '')}"></div>`,
          async () => {
            const rr = await api('/api/sys/role/save', 'POST', { id, name: $('#f-name').value.trim(), remark: $('#f-remark').value });
            if (rr.code !== 0) throw new Error(rr.msg);
            load();
          });
      }
      if (act === 'perm') {
        const d = await api('/api/sys/role/menus?role_id=' + id);
        const treeHtml = (list, depth = 0) => list.map(m => `
          <div class="form-check" style="margin-left:${depth * 22}px">
            <input class="form-check-input perm-ck" type="checkbox" value="${m.id}" id="m${m.id}"
              ${d.data.ids.includes(m.id) ? 'checked' : ''}>
            <label class="form-check-label" for="m${m.id}">${esc(m.name)} <span class="text-muted small">(${esc(m.perm)})</span></label>
          </div>` + treeHtml(m.children || [], depth + 1)).join('');
        return dlg(`分配权限 - ${b.dataset.name}`, `<div class="mb-2 small text-muted">勾选该角色可见的菜单：</div>${treeHtml(d.data.tree)}`,
          async () => {
            const ids = [...document.querySelectorAll('.perm-ck:checked')].map(c => +c.value);
            const rr = await api('/api/sys/role/saveMenus', 'POST', { role_id: id, menu_ids: ids });
            if (rr.code !== 0) throw new Error(rr.msg);
          });
      }
      if (act === 'del') return confirmBox('确定删除该角色？', async () => {
        const rr = await api('/api/sys/role/delete', 'POST', { id });
        if (rr.code !== 0) throw new Error(rr.msg);
        alert(rr.data || rr.msg);
        load();
      });
    });
  };
  $('#r-add').onclick = () => dlg('新增角色', `
      <div class="mb-2"><label class="form-label">角色名</label><input id="f-name" class="form-control"></div>
      <div><label class="form-label">备注</label><input id="f-remark" class="form-control"></div>`,
    async () => {
      const r = await api('/api/sys/role/save', 'POST', { name: $('#f-name').value.trim(), remark: $('#f-remark').value });
      if (r.code !== 0) throw new Error(r.msg);
      load();
    });
  load();
}

/* ================= 部门管理（树形表格） ================= */
function renderDept(el) {
  el.innerHTML = `
    <div class="mb-2"><button id="d-add" class="btn btn-sm btn-outline-success">＋ 新增部门</button></div>
    <table class="table table-sm table-hover align-middle bg-white">
      <thead class="table-light"><tr><th>名称</th><th>排序</th><th style="width:250px">操作</th></tr></thead>
      <tbody id="d-rows"></tbody></table>`;

  const load = async () => {
    const r = await api('/api/sys/dept/tree');
    const rows = [];
    const walk = (list, depth) => list.forEach(d => {
      rows.push({ d, depth });
      walk(d.children || [], depth + 1);
    });
    walk(r.data, 0);
    $('#d-rows').innerHTML = rows.map(({ d, depth }) => `<tr>
      <td style="padding-left:${18 + depth * 24}px">${depth ? '└ ' : ''}${esc(d.name)}</td><td>${d.sort}</td>
      <td>
        <button class="btn btn-sm btn-outline-success me-1" data-act="addsub" data-id="${d.id}">新增子部门</button>
        <button class="btn btn-sm btn-outline-primary me-1" data-act="edit" data-x='${esc(JSON.stringify(d))}'>编辑</button>
        <button class="btn btn-sm btn-outline-danger" data-act="del" data-id="${d.id}">删除</button>
      </td></tr>`).join('');
    $('#d-rows').querySelectorAll('button').forEach(b => b.onclick = async () => {
      const act = b.dataset.act, id = +b.dataset.id;
      const form = (parentHtml, name, sort) => `
        <div class="mb-2"><label class="form-label">上级部门</label>${parentHtml}</div>
        <div class="mb-2"><label class="form-label">名称</label><input id="f-name" class="form-control" value="${esc(name)}"></div>
        <div><label class="form-label">排序</label><input id="f-sort" type="number" class="form-control" value="${sort}"></div>`;
      if (act === 'addsub') {
        return dlg('新增子部门', form(`<input class="form-control" disabled value="ID ${id}">`, '', 0),
          async () => {
            const rr = await api('/api/sys/dept/save', 'POST', { parent_id: id, name: $('#f-name').value.trim(), sort: +$('#f-sort').value });
            if (rr.code !== 0) throw new Error(rr.msg);
            load();
          });
      }
      if (act === 'edit') {
        const d = JSON.parse(b.dataset.x);
        return dlg('编辑部门', form(`<input class="form-control" disabled value="ID ${d.parent_id}">`, d.name, d.sort),
          async () => {
            const rr = await api('/api/sys/dept/save', 'POST', { id: d.id, parent_id: d.parent_id, name: $('#f-name').value.trim(), sort: +$('#f-sort').value });
            if (rr.code !== 0) throw new Error(rr.msg);
            load();
          });
      }
      if (act === 'del') return confirmBox('删除前会校验子节点，确定删除？', async () => {
        const rr = await api('/api/sys/dept/delete', 'POST', { id });
        if (rr.code !== 0) throw new Error(rr.msg);
        alert(rr.data || rr.msg);
        load();
      });
    });
  };
  $('#d-add').onclick = () => dlg('新增部门', `
      <div class="mb-2"><label class="form-label">名称</label><input id="f-name" class="form-control"></div>
      <div><label class="form-label">排序</label><input id="f-sort" type="number" class="form-control" value="0"></div>`,
    async () => {
      const r = await api('/api/sys/dept/save', 'POST', { parent_id: 0, name: $('#f-name').value.trim(), sort: +$('#f-sort').value });
      if (r.code !== 0) throw new Error(r.msg);
      load();
    });
  load();
}

/* ================= 菜单管理（树形列表） ================= */
function renderMenu(el) {
  el.innerHTML = `
    <div class="mb-2"><button id="m-add" class="btn btn-sm btn-outline-success">＋ 新增菜单</button></div>
    <table class="table table-sm table-hover align-middle bg-white">
      <thead class="table-light"><tr><th>名称</th><th>类型</th><th>权限标识</th><th>显示/隐藏</th><th>排序</th><th style="width:180px">操作</th></tr></thead>
      <tbody id="m-rows"></tbody></table>`;

  const load = async () => {
    const r = await api('/api/sys/menu/tree');
    const rows = [];
    const walk = (list, depth) => list.forEach(m => { rows.push({ m, depth }); walk(m.children || [], depth + 1); });
    walk(r.data, 0);
    $('#m-rows').innerHTML = rows.map(({ m, depth }) => `<tr>
      <td style="padding-left:${18 + depth * 24}px">${esc(m.name)}</td>
      <td><span class="badge bg-info badge-sm">${esc(m.type)}</span></td>
      <td><code>${esc(m.perm || '-')}</code></td>
      <td>${m.visible === 1 ? '显示' : '<span class="text-muted">隐藏</span>'}</td><td>${m.sort}</td>
      <td>
        <button class="btn btn-sm btn-outline-primary me-1" data-x='${esc(JSON.stringify(m))}'>编辑</button>
        <button class="btn btn-sm btn-outline-danger" data-id="${m.id}">删除</button>
      </td></tr>`).join('');
    $('#m-rows').querySelectorAll('button.btn-outline-primary').forEach(b => b.onclick = () => {
      const m = JSON.parse(b.dataset.x);
      menuForm(m);
    });
    $('#m-rows').querySelectorAll('button.btn-outline-danger').forEach(b => b.onclick = () => confirmBox('确定删除该菜单？', async () => {
      const rr = await api('/api/sys/menu/delete', 'POST', { id: +b.dataset.id });
      if (rr.code !== 0) throw new Error(rr.msg);
      alert(rr.data || rr.msg);
      load();
    }));
  };

  function menuForm(m = null) {
    dlg(m ? '编辑菜单' : '新增菜单', `
      <div class="mb-2"><label class="form-label">名称</label><input id="f-name" class="form-control" value="${esc(m?.name || '')}"></div>
      <div class="mb-2"><label class="form-label">类型</label>
        <select id="f-type" class="form-select">${['目录', '菜单', '按钮'].map(t => `<option ${m?.type === t ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
      <div class="mb-2"><label class="form-label">权限标识</label><input id="f-perm" class="form-control" value="${esc(m?.perm || '')}" placeholder="如 sys:user"></div>
      <div class="mb-2 d-flex gap-3">
        <div><label class="form-label">排序</label><input id="f-sort" type="number" class="form-control" value="${m?.sort ?? 0}"></div>
        <div><label class="form-label">显示</label><select id="f-visible" class="form-select">
          <option value="1" ${m?.visible !== 0 ? 'selected' : ''}>显示</option><option value="0" ${m?.visible === 0 ? 'selected' : ''}>隐藏</option></select></div>
      </div>`,
      async () => {
        const body = {
          id: m?.id, name: $('#f-name').value.trim(), type: $('#f-type').value, perm: $('#f-perm').value.trim(),
          sort: +$('#f-sort').value, visible: +$('#f-visible').value, parent_id: m?.parent_id ?? 0,
        };
        const r = await api('/api/sys/menu/save', 'POST', body);
        if (r.code !== 0) throw new Error(r.msg);
        load();
      });
  }
  $('#m-add').onclick = () => menuForm();
  load();
}

/* ================= 字典管理（两级：类型 → 字典项） ================= */
function renderDict(el) {
  el.innerHTML = `<div class="row g-3">
    <div class="col-md-4">
      <div class="d-flex mb-2"><button id="dt-add" class="btn btn-sm btn-outline-success">＋ 新增类型</button></div>
      <table class="table table-sm table-hover bg-white"><thead class="table-light"><tr><th>类型</th><th>编码</th><th style="width:130px">操作</th></tr></thead>
      <tbody id="dt-rows"></tbody></table>
    </div>
    <div class="col-md-8">
      <div class="d-flex mb-2 align-items-center"><span class="me-2 small text-muted" id="di-title">（点击左侧类型查看字典项）</span>
        <button id="di-add" class="btn btn-sm btn-outline-success d-none">＋ 新增字典项</button></div>
      <table class="table table-sm table-hover bg-white"><thead class="table-light"><tr><th>标签</th><th>值</th><th>排序</th><th style="width:130px">操作</th></tr></thead>
      <tbody id="di-rows"></tbody></table>
    </div></div>`;
  let cur = '';

  const loadTypes = async (keepPick) => {
    const r = await api('/api/sys/dict/types');
    $('#dt-rows').innerHTML = r.data.map(t => `<tr class="pointer ${t.code === cur ? 'table-success' : ''}" data-code="${t.code}" data-x='${esc(JSON.stringify(t))}'>
      <td>${esc(t.name)}</td><td><code>${esc(t.code)}</code></td>
      <td><button class="btn btn-sm btn-outline-danger" data-code="${t.code}">删除</button></td></tr>`).join('');
    $('#dt-rows').querySelectorAll('tr').forEach(tr => tr.onclick = e => {
      if (e.target.tagName === 'BUTTON') return;
      cur = tr.dataset.code;
      $('#di-title').textContent = `类型「${JSON.parse(tr.dataset.x).name}」的字典项`;
      $('#di-add').classList.remove('d-none');
      loadTypes(true);
      loadItems();
    });
    $('#dt-rows').querySelectorAll('button').forEach(b => b.onclick = () => confirmBox('删除类型会连同字典项一起删除，确定？', async () => {
      const rr = await api('/api/sys/dict/typeDelete', 'POST', { code: b.dataset.code });
      if (rr.code !== 0) throw new Error(rr.msg);
      cur = '';
      loadTypes();
    }));
    if (keepPick && cur) loadItems();
  };

  const loadItems = async () => {
    if (!cur) return;
    const r = await api('/api/sys/dict/items?code=' + encodeURIComponent(cur));
    $('#di-rows').innerHTML = r.data.map(i => `<tr>
      <td>${esc(i.label)}</td><td><code>${esc(i.value)}</code></td><td>${i.sort}</td>
      <td>
        <button class="btn btn-sm btn-outline-primary me-1" data-x='${esc(JSON.stringify(i))}'>编辑</button>
        <button class="btn btn-sm btn-outline-danger" data-id="${i.id}">删除</button>
      </td></tr>`).join('');
    $('#di-rows').querySelectorAll('button.btn-outline-primary').forEach(b => b.onclick = () => itemForm(JSON.parse(b.dataset.x)));
    $('#di-rows').querySelectorAll('button.btn-outline-danger').forEach(b => b.onclick = () => confirmBox('确定删除该字典项？', async () => {
      const rr = await api('/api/sys/dict/itemDelete', 'POST', { id: +b.dataset.id });
      if (rr.code !== 0) throw new Error(rr.msg);
      loadItems();
    }));
  };

  const itemForm = (i = null) => dlg(i ? '编辑字典项' : '新增字典项', `
      <div class="mb-2"><label class="form-label">标签</label><input id="f-label" class="form-control" value="${esc(i?.label || '')}"></div>
      <div class="mb-2"><label class="form-label">值</label><input id="f-value" class="form-control" value="${esc(i?.value || '')}"></div>
      <div><label class="form-label">排序</label><input id="f-sort" type="number" class="form-control" value="${i?.sort ?? 0}"></div>`,
    async () => {
      const r = await api('/api/sys/dict/itemSave', 'POST',
        { id: i?.id, type_code: cur, label: $('#f-label').value.trim(), value: $('#f-value').value.trim(), sort: +$('#f-sort').value });
      if (r.code !== 0) throw new Error(r.msg);
      loadItems();
    });

  $('#dt-add').onclick = () => dlg('新增字典类型', `
      <div class="mb-2"><label class="form-label">名称</label><input id="f-name" class="form-control"></div>
      <div><label class="form-label">编码</label><input id="f-code" class="form-control" placeholder="如 source"></div>`,
    async () => {
      const r = await api('/api/sys/dict/typeSave', 'POST', { name: $('#f-name').value.trim(), code: $('#f-code').value.trim() });
      if (r.code !== 0) throw new Error(r.msg);
      alert(r.data || r.msg);
      loadTypes();
    });
  $('#di-add').onclick = () => itemForm();
  loadTypes();
}

/* ================= 附件管理 ================= */
function renderAttach(el) {
  let page = 1;
  el.innerHTML = `
    <div class="d-flex flex-wrap gap-2 mb-2">
      <input id="a-kw" class="form-control form-control-sm w-auto" placeholder="文件名关键词">
      <select id="a-module" class="form-select form-select-sm w-auto">
        <option value="">全部来源模块</option><option value="doc">doc</option>
      </select>
      <button id="a-search" class="btn btn-sm btn-success">查询</button>
    </div>
    <div class="table-responsive"><table class="table table-sm table-hover align-middle bg-white">
      <thead class="table-light"><tr><th>ID</th><th>文件名</th><th>大小</th><th>MD5</th><th>来源模块</th><th>关联状态</th><th>时间</th><th style="width:210px">操作</th></tr></thead>
      <tbody id="a-rows"></tbody></table></div>
    <div id="a-page"></div>`;

  const load = async () => {
    const r = await api(`/api/sys/attach/list?page=${page}&size=15&keyword=${encodeURIComponent($('#a-kw').value)}&module=${$('#a-module').value}`);
    $('#a-rows').innerHTML = r.data.rows.map(a => `<tr>
      <td>${a.id}</td><td>${esc(a.file_name)}</td><td>${fmtSize(a.file_size)}</td>
      <td class="small text-muted">${(a.file_md5 || '').slice(0, 10)}…</td>
      <td><a href="#" class="module-edit pointer" data-id="${a.id}" data-m="${esc(a.source_module || '')}">${esc(a.source_module || '-')}</a></td>
      <td>${a.kid ? bdg(REVIEW, a.review_status) + ' ' + bdg(VECTOR, a.vector_status) : '-'}</td>
      <td class="small">${esc((a.created_at || '').slice(0, 19))}</td>
      <td>
        <button class="btn btn-sm btn-outline-primary me-1" data-act="view" data-id="${a.id}">预览</button>
        <button class="btn btn-sm btn-outline-secondary me-1" data-act="dl" data-id="${a.id}">下载</button>
        <button class="btn btn-sm btn-outline-danger" data-act="del" data-id="${a.id}">删除</button>
      </td></tr>`).join('');
    pager($('#a-page'), r.data.total, page, 15, p => { page = p; load(); });
    $('#a-rows').querySelectorAll('button').forEach(b => b.onclick = () => {
      const id = b.dataset.id;
      if (b.dataset.act === 'del') return confirmBox('删除附件会同时删除落盘文件，确定？', async () => {
        const rr = await api('/api/sys/attach/delete', 'POST', { id: +id });
        if (rr.code !== 0) throw new Error(rr.msg);
        alert(rr.data || rr.msg);
        load();
      });
      window.open('/api/sys/attach/download?id=' + id + '&token=' + encodeURIComponent(TOKEN));   // 预览 / 下载同源
    });
    $('#a-rows').querySelectorAll('.module-edit').forEach(a => a.onclick = e => {
      e.preventDefault();
      dlg('设置来源模块（为资料解析预留）',
        `<div><label class="form-label">模块标识</label><input id="f-module" class="form-control" value="${esc(a.dataset.m)}" placeholder="如 doc / kb / qa"></div>`,
        async () => {
          const r2 = await api('/api/sys/attach/setModule', 'POST', { id: +a.dataset.id, module: $('#f-module').value.trim() });
          if (r2.code !== 0) throw new Error(r2.msg);
          load();
        });
    });
  };
  $('#a-search').onclick = () => { page = 1; load(); };
  load();
}

/* ================= 参数配置 ================= */
function renderConfig(el) {
  el.innerHTML = `
    <div class="mb-2"><button id="c-add" class="btn btn-sm btn-outline-success">＋ 新增参数</button></div>
    <table class="table table-sm table-hover align-middle bg-white">
      <thead class="table-light"><tr><th>参数名</th><th>键</th><th>值</th><th>内置</th><th style="width:180px">操作</th></tr></thead>
      <tbody id="c-rows"></tbody></table>`;
  const load = async () => {
    const r = await api('/api/sys/config/list');
    $('#c-rows').innerHTML = r.data.map(c => `<tr>
      <td>${esc(c.name)}</td><td><code>${esc(c.cfg_key)}</code></td><td>${esc(c.cfg_value)}</td>
      <td>${c.builtin ? '<span class="badge bg-secondary badge-sm">内置</span>' : '-'}</td>
      <td>
        <button class="btn btn-sm btn-outline-primary me-1" data-x='${esc(JSON.stringify(c))}'>编辑</button>
        ${c.builtin ? '' : `<button class="btn btn-sm btn-outline-danger" data-id="${c.id}">删除</button>`}
      </td></tr>`).join('');
    $('#c-rows').querySelectorAll('button.btn-outline-primary').forEach(b => b.onclick = () => {
      const c = JSON.parse(b.dataset.x);
      dlg('编辑参数', `
        <div class="mb-2"><label class="form-label">参数名</label><input id="f-name" class="form-control" value="${esc(c.name)}"></div>
        <div class="mb-2"><label class="form-label">键</label><input class="form-control" value="${esc(c.cfg_key)}" disabled></div>
        <div><label class="form-label">值</label><input id="f-value" class="form-control" value="${esc(c.cfg_value)}"></div>`,
        async () => {
          const rr = await api('/api/sys/config/save', 'POST', { id: c.id, name: $('#f-name').value.trim(), cfg_key: c.cfg_key, cfg_value: $('#f-value').value });
          if (rr.code !== 0) throw new Error(rr.msg);
          load();
        });
    });
    $('#c-rows').querySelectorAll('button.btn-outline-danger').forEach(b => b.onclick = () => confirmBox('确定删除该参数？', async () => {
      const rr = await api('/api/sys/config/delete', 'POST', { id: +b.dataset.id });
      if (rr.code !== 0) throw new Error(rr.msg);
      alert(rr.data || rr.msg);
      load();
    }));
  };
  $('#c-add').onclick = () => dlg('新增参数', `
      <div class="mb-2"><label class="form-label">参数名</label><input id="f-name" class="form-control"></div>
      <div class="mb-2"><label class="form-label">键</label><input id="f-key" class="form-control" placeholder="如 qa.topk"></div>
      <div><label class="form-label">值</label><input id="f-value" class="form-control"></div>`,
    async () => {
      const r = await api('/api/sys/config/save', 'POST',
        { name: $('#f-name').value.trim(), cfg_key: $('#f-key').value.trim(), cfg_value: $('#f-value').value });
      if (r.code !== 0) throw new Error(r.msg);
      alert(r.data || r.msg);
      load();
    });
  load();
}

/* ================= 登录日志 ================= */
function renderLoginLog(el) {
  let page = 1;
  el.innerHTML = `
    <div class="mb-2 d-flex gap-2">
      <button id="l-clear" class="btn btn-sm btn-outline-danger">清空</button>
      <button id="l-export" class="btn btn-sm btn-outline-secondary">导出</button>
    </div>
    <div class="table-responsive"><table class="table table-sm table-hover align-middle bg-white">
      <thead class="table-light"><tr><th>ID</th><th>用户名</th><th>IP</th><th>结果</th><th>说明</th><th>时间</th></tr></thead>
      <tbody id="l-rows"></tbody></table></div>
    <div id="l-page"></div>`;
  const load = async () => {
    const r = await api(`/api/sys/loginlog/list?page=${page}&size=15`);
    $('#l-rows').innerHTML = r.data.rows.map(x => `<tr>
      <td>${x.id}</td><td>${esc(x.username)}</td><td>${esc(x.ip)}</td>
      <td>${x.ok ? '<span class="badge bg-success badge-sm">成功</span>' : '<span class="badge bg-danger badge-sm">失败</span>'}</td>
      <td>${esc(x.msg)}</td><td class="small">${esc((x.created_at || '').slice(0, 19))}</td></tr>`).join('');
    pager($('#l-page'), r.data.total, page, 15, p => { page = p; load(); });
  };
  $('#l-clear').onclick = () => confirmBox('确定清空全部登录日志？', async () => {
    const r = await api('/api/sys/loginlog/clear', 'POST', {});
    if (r.code !== 0) throw new Error(r.msg);
    load();
  });
  $('#l-export').onclick = () => downloadCsv('/api/sys/loginlog/export', 'login_logs.csv');
  load();
}

/* ================= 操作日志 ================= */
function renderOperLog(el) {
  let page = 1;
  el.innerHTML = `
    <div class="mb-2 d-flex gap-2">
      <input id="o-kw" class="form-control form-control-sm w-auto" placeholder="路径/用户名">
      <button id="o-search" class="btn btn-sm btn-success">查询</button>
    </div>
    <div class="table-responsive"><table class="table table-sm table-hover align-middle bg-white">
      <thead class="table-light"><tr><th>ID</th><th>用户</th><th>方法</th><th>路径</th><th>状态</th><th>时间</th><th>操作</th></tr></thead>
      <tbody id="o-rows"></tbody></table></div>
    <div id="o-page"></div>`;
  const load = async () => {
    const r = await api(`/api/sys/operlog/list?page=${page}&size=15&keyword=${encodeURIComponent($('#o-kw').value)}`);
    $('#o-rows').innerHTML = r.data.rows.map(x => `<tr>
      <td>${x.id}</td><td>${esc(x.username)}</td><td>${esc(x.method)}</td><td><code>${esc(x.path)}</code></td>
      <td>${x.status === 200 ? '<span class="badge bg-success badge-sm">200</span>' : `<span class="badge bg-warning badge-sm">${x.status}</span>`}</td>
      <td class="small">${esc((x.created_at || '').slice(0, 19))}</td>
      <td><button class="btn btn-sm btn-outline-primary" data-id="${x.id}">详情</button></td></tr>`).join('');
    pager($('#o-page'), r.data.total, page, 15, p => { page = p; load(); });
    $('#o-rows').querySelectorAll('button').forEach(b => b.onclick = async () => {
      const d = await api('/api/sys/operlog/detail?id=' + b.dataset.id);
      dlg('操作日志详情 #' + b.dataset.id, `
        <table class="table table-sm"><tbody>
          <tr><th style="width:90px">用户</th><td>${esc(d.data.username)}</td></tr>
          <tr><th>请求</th><td>${esc(d.data.method)} ${esc(d.data.path)}</td></tr>
          <tr><th>请求参数</th><td style="word-break:break-all"><pre class="mb-0 small">${esc(d.data.params)}</pre></td></tr>
          <tr><th>返回结果</th><td>${esc(d.data.result)}</td></tr>
          <tr><th>时间</th><td>${esc((d.data.created_at || '').slice(0, 19))}</td></tr>
        </tbody></table>`, async () => true);
    });
  };
  $('#o-search').onclick = () => { page = 1; load(); };
  load();
}

/* ---------------- 启动 ---------------- */
init().catch(e => console.error(e));
