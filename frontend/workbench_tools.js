/*
 * 训练工作台 · 配置导入 / 保存
 *
 * 由后端注入到 index.html（见 mikazuki/app/application.py 的 render_index），
 * 文件放在 frontend/ 而不是 frontend/dist/，因此前端整目录升级不会把它删掉。
 *
 * 导入：把 train.toml 交给 /api/v2/drafts/import 按当前训练器的参数目录逐键对应，
 *       结果写进工作台自己的草稿后重新载入一次页面，中间的表单就变成导入的值。
 * 保存：把当前草稿交给 /api/v2/compile 生成 train.toml，连同数据集表一起下载。
 */
(function () {
  'use strict';

  var DRAFTS_KEY = 'ls-v2-drafts';
  var SELECTED_KEY = 'ls-v2-selected-trainer';
  var IMPORT_URL = '/api/v2/drafts/import';
  var COMPILE_URL = '/api/v2/compile?persist=false&validate_paths=false';
  var TOAST_FLAG = 'wbt-pending-toast';

  if (window.__workbenchConfigToolsInstalled) return;
  window.__workbenchConfigToolsInstalled = true;

  // ---------- 存取 ----------

  function readDrafts() {
    try {
      var raw = localStorage.getItem(DRAFTS_KEY);
      var parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
    } catch (err) {
      return {};
    }
  }

  function writeDraft(trainerId, draft) {
    var drafts = readDrafts();
    drafts[trainerId] = draft;
    localStorage.setItem(DRAFTS_KEY, JSON.stringify(drafts));
    localStorage.setItem(SELECTED_KEY, trainerId);
  }

  function selectedTrainerId() {
    try {
      return localStorage.getItem(SELECTED_KEY) || '';
    } catch (err) {
      return '';
    }
  }

  // 工作台的草稿 store：Pinia 挂在 Vue 应用实例上，这里只读取、不修改前端代码。
  function draftStore() {
    var root = document.querySelector('#app');
    var app = root && root.__vue_app__;
    var pinia = app && app.config && app.config.globalProperties && app.config.globalProperties.$pinia;
    var stores = pinia && pinia._s;
    return stores && stores.get ? stores.get('draft') : null;
  }

  // ---------- 提示 ----------

  var toastTimer = null;

  function toast(message, kind) {
    var el = document.getElementById('wbt-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'wbt-toast';
      document.body.appendChild(el);
    }
    el.textContent = message;
    el.dataset.kind = kind || 'info';
    el.classList.add('is-visible');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      el.classList.remove('is-visible');
    }, kind === 'error' ? 8000 : 3800);
  }

  // 导入后页面要重新载入一次（见 applyDraft 的说明），提示语先寄存，载入完成后再显示。
  function queueToast(message, kind) {
    try {
      sessionStorage.setItem(TOAST_FLAG, JSON.stringify({ text: message, kind: kind || 'ok' }));
    } catch (err) {
      /* 私密模式下 sessionStorage 不可用，提示丢掉即可 */
    }
  }

  function flushToast() {
    var raw = null;
    try {
      raw = sessionStorage.getItem(TOAST_FLAG);
      if (raw) sessionStorage.removeItem(TOAST_FLAG);
    } catch (err) {
      return;
    }
    if (!raw) return;
    var payload = null;
    try {
      payload = JSON.parse(raw);
    } catch (err) {
      return;
    }
    if (payload && payload.text) toast(payload.text, payload.kind);
  }

  function describe(list) {
    return (list || [])
      .slice(0, 4)
      .map(function (item) {
        return (item.field ? item.field + '：' : '') + (item.message || item.code || '');
      })
      .join('\n');
  }

  function postJson(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(function (res) {
      return res.json().then(function (data) {
        return { ok: res.ok, status: res.status, data: data };
      });
    });
  }

  // 训练器目录：扁平参数表（resetForTrainer/persistForTrainer 都要用）+ 数据集默认值。
  function loadCatalog(trainerId) {
    var base = '/api/v2/trainers/' + encodeURIComponent(trainerId);
    return Promise.all([
      fetch(base).then(function (res) { return res.json(); }),
      fetch(base + '/params?view=all').then(function (res) { return res.json(); }),
    ]).then(function (pair) {
      var trainer = pair[0] || {};
      var catalog = pair[1] || {};
      var flat = [];
      (catalog.groups || []).forEach(function (group) {
        (group.params || []).forEach(function (param) { flat.push(param); });
      });
      return {
        params: flat,
        datasetDefaults: trainer.datasetDefaults || {},
        manifestHash: catalog.manifestHash || trainer.manifestHash || '',
      };
    });
  }

  // ---------- 导入 ----------

  function pickFile() {
    var input = document.createElement('input');
    input.type = 'file';
    input.accept = '.toml,.txt';
    input.style.display = 'none';
    document.body.appendChild(input);
    input.addEventListener('change', function () {
      var file = input.files && input.files[0];
      document.body.removeChild(input);
      if (file) importFile(file);
    });
    input.click();
  }

  function importFile(file) {
    var trainerId = selectedTrainerId();
    if (!trainerId) {
      toast('先在左侧选一个训练器，再导入配置', 'error');
      return;
    }
    toast('正在读取 ' + file.name + '…', 'info');

    var reader = new FileReader();
    reader.onerror = function () {
      toast('读取文件失败：' + file.name, 'error');
    };
    reader.onload = function () {
      var baseName = file.name.replace(/\.(toml|txt)$/i, '');
      postJson(IMPORT_URL, { trainerId: trainerId, toml: String(reader.result || ''), name: baseName })
        .then(function (result) {
          var data = result.data || {};
          if (!result.ok) {
            toast('导入失败：' + (data.detail || '服务返回 ' + result.status), 'error');
            return;
          }
          var errors = data.errors || [];
          if (errors.length) {
            toast('这份配置有 ' + errors.length + ' 处问题，未写入：\n' + describe(errors), 'error');
            return;
          }
          applyDraft(trainerId, data);
        })
        .catch(function (err) {
          toast('导入失败：' + err.message, 'error');
        });
    };
    reader.readAsText(file, 'utf-8');
  }

  // 把导入结果写进工作台自己的草稿，重新载入后表单就是导入的值。
  function applyDraft(trainerId, result) {
    var draft = Object.assign({}, result.draft);
    draft.savedAt = new Date().toISOString();
    try {
      writeDraft(trainerId, draft);
    } catch (err) {
      toast('写入浏览器存储失败：' + err.message, 'error');
      return;
    }

    var store = draftStore();
    var summary = ['已导入 ' + (result.mappedCount || 0) + ' 项'];
    if (result.skippedCount) summary.push('跳过 ' + result.skippedCount + ' 项');
    if (result.unknownCount) summary.push(result.unknownCount + ' 项未识别');
    queueToast(summary.join('，'), 'ok');

    // 只调 store 是不够的：工作台的表单控件在用户手动输入后会把值缓在控件自己身上，
    // 草稿改了它也不跟着显示（实测把重复次数手改成 9 之后再导入，store 与存储都已是 3，
    // 输入框仍显示 9）。所以这里先把草稿写进 store，再重新载入页面，
    // 让工作台按刚才写好的草稿把整个表单重建成导入后的值。
    function reloadAfterApply(delay) {
      setTimeout(function () {
        location.reload();
      }, delay);
    }

    if (!store) {
      reloadAfterApply(150);
      return;
    }

    loadCatalog(trainerId)
      .then(function (catalog) {
        if (!catalog.params.length) throw new Error('训练器参数目录为空');
        store.resetForTrainer(
          catalog.params,
          trainerId,
          result.manifestHash || catalog.manifestHash,
          true,
          catalog.datasetDefaults,
        );
        store.persistForTrainer(trainerId, catalog.params);
      })
      .catch(function () {
        /* 回填失败也没关系，存储里已经有正确的草稿，重新载入即可 */
      })
      .then(function () {
        reloadAfterApply(250);
      });
  }

  // ---------- 保存 ----------

  function download(filename, text) {
    var blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 2000);
  }

  function safeName(value) {
    var text = String(value || '').trim() || 'train_config';
    return text.replace(/[\\/:*?"<>|]+/g, '_');
  }

  // 数据集设置拼在训练配置后面，导出的文件才能被导入端完整读回。
  // [general] 放在 [[datasets]] 前面，读起来和 sd-scripts 的 dataset.toml 一致。
  function orderDatasetTables(datasetConfig) {
    var text = String(datasetConfig || '').trim();
    if (!text) return '';
    var blocks = [];
    var current = [];
    text.split(/\r?\n/).forEach(function (line) {
      if (/^\s*\[/.test(line) && current.length) {
        blocks.push(current);
        current = [];
      }
      current.push(line);
    });
    if (current.length) blocks.push(current);

    var general = [];
    var rest = [];
    blocks.forEach(function (block) {
      var head = block.find(function (line) { return /^\s*\[/.test(line); }) || '';
      if (/^\s*\[general\]/.test(head)) general = general.concat(block);
      else rest = rest.concat(block);
    });
    return general.concat(rest).join('\n').replace(/\n{3,}/g, '\n\n').trim();
  }

  // 编译产物里 [dataset] 只放本次运行生成的 dataset.toml 路径，导出时没有意义
  // （重新导入时也会被忽略），直接去掉，免得把临时 run 目录写进配置快照。
  function stripDatasetSection(trainConfig) {
    var lines = String(trainConfig || '').split(/\r?\n/);
    var out = [];
    var skipping = false;
    lines.forEach(function (line) {
      if (/^\s*\[/.test(line)) skipping = /^\s*\[dataset\]\s*$/.test(line);
      if (!skipping) out.push(line);
    });
    return out.join('\n').replace(/\n{3,}/g, '\n\n').replace(/\s+$/, '');
  }

  function mergeDatasetTables(trainConfig, datasetConfig) {
    var head = [
      '# 训练工作台配置快照',
      '# 上面是训练参数；下面的 [general] 与 [[datasets]] 来自同一份草稿的数据集设置，',
      '# 合在一起是为了让这个文件能原样导入回工作台。',
      '',
    ].join('\n');
    var body = stripDatasetSection(trainConfig);
    var extra = orderDatasetTables(datasetConfig);
    return extra ? head + body + '\n\n# ---- 数据集 ----\n' + extra + '\n' : head + body + '\n';
  }

  function buildPayload(trainerId) {
    var store = draftStore();
    if (store && typeof store.buildDraft === 'function') {
      var built = store.buildDraft(trainerId);
      if (built && typeof built === 'object') {
        built.trainerId = trainerId;
        return built;
      }
    }
    var draft = readDrafts()[trainerId];
    if (!draft) return null;
    return {
      trainerId: trainerId,
      name: draft.name,
      modelAssets: draft.modelAssets || {},
      dataset: draft.dataset || {},
      params: draft.params || {},
      runtime: draft.runtime || {},
      sample: draft.sample || {},
    };
  }

  function saveConfig() {
    var trainerId = selectedTrainerId();
    if (!trainerId) {
      toast('先选一个训练器再保存配置', 'error');
      return;
    }
    var payload = buildPayload(trainerId);
    if (!payload) {
      toast('当前训练器还没有草稿，先填参数再保存', 'error');
      return;
    }
    payload.trainerId = trainerId;

    toast('正在生成配置…', 'info');
    postJson(COMPILE_URL, payload)
      .then(function (result) {
        var data = result.data || {};
        if (!result.ok) {
          toast('生成配置失败：' + (data.detail || '服务返回 ' + result.status), 'error');
          return;
        }
        var blocking = (data.errors || []).filter(function (item) {
          return (item.severity || 'error') === 'error' && (item.code || '') !== 'path.missing';
        });
        if (blocking.length) {
          toast('配置有 ' + blocking.length + ' 处错误，先修好再保存：\n' + describe(blocking), 'error');
          return;
        }

        var trainConfig = data.trainConfig || (data.artifacts && data.artifacts.trainConfig) || '';
        var datasetConfig = data.datasetConfig || (data.artifacts && data.artifacts.datasetConfig) || '';
        if (!trainConfig) {
          toast('服务没有返回训练配置', 'error');
          return;
        }

        var filename = safeName(payload.name || trainerId) + '.toml';
        download(filename, mergeDatasetTables(trainConfig, datasetConfig));
        toast('已保存 ' + filename, 'ok');
      })
      .catch(function (err) {
        toast('生成配置失败：' + err.message, 'error');
      });
  }

  // ---------- 界面 ----------

  var STYLE = [
    // 侧边栏（aside）是 position:fixed;z-index:50 且不透明，面板必须压在它上面才看得见。
    '#wbt-tools{position:fixed;z-index:2147483000;display:grid;gap:4px;pointer-events:none}',
    '#wbt-tools .wbt-btn{',
    '  pointer-events:auto;display:flex;align-items:center;gap:8px;width:100%;',
    '  min-height:36px;padding:6px 10px;border:1px solid transparent;border-radius:11px;',
    '  background:transparent;color:var(--text-secondary,#606266);',
    '  font:inherit;font-size:13px;line-height:1.2;text-align:left;cursor:pointer;',
    '  transition:color .16s,background-color .16s,border-color .16s;',
    '}',
    '#wbt-tools .wbt-btn:hover,#wbt-tools .wbt-btn:focus-visible{',
    '  background:var(--surface-hover,rgba(0,0,0,.04));',
    '  color:var(--text-strong,var(--text,#303133));border-color:var(--border-subtle,transparent);',
    '}',
    '#wbt-tools .wbt-btn:active{background:var(--brand-soft,rgba(64,158,255,.12))}',
    '#wbt-tools svg{width:15px;height:15px;flex:none;stroke:currentColor;fill:none;',
    '  stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}',
    '#wbt-tools .wbt-label{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '#wbt-tools.is-compact .wbt-label{display:none}',
    '#wbt-tools.is-compact .wbt-btn{justify-content:center;padding-inline:0}',
    '#wbt-toast{',
    '  position:fixed;z-index:60;left:16px;bottom:16px;max-width:min(440px,80vw);',
    '  padding:10px 14px;border-radius:10px;white-space:pre-wrap;',
    '  font:13px/1.55 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;',
    '  background:#303133;color:#fff;box-shadow:0 6px 24px rgba(0,0,0,.18);',
    '  opacity:0;transform:translateY(6px);pointer-events:none;',
    '  transition:opacity .18s,transform .18s;',
    '}',
    '#wbt-toast.is-visible{opacity:1;transform:translateY(0)}',
    '#wbt-toast[data-kind=error]{background:#c45656}',
    '#wbt-toast[data-kind=ok]{background:#3f7d43}',
  ].join('\n');

  var ICON_IMPORT =
    '<svg viewBox="0 0 24 24" aria-hidden="true">' +
    '<path d="M12 3v10"/><path d="m8 9 4 4 4-4"/>' +
    '<path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg>';
  var ICON_EXPORT =
    '<svg viewBox="0 0 24 24" aria-hidden="true">' +
    '<path d="M12 13V3"/><path d="m8 7 4-4 4 4"/>' +
    '<path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg>';

  var panel = null;

  function makeButton(label, icon, handler) {
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'wbt-btn';
    button.title = label;
    button.setAttribute('aria-label', label);
    button.innerHTML = icon + '<span class="wbt-label"></span>';
    button.querySelector('.wbt-label').textContent = label;
    button.addEventListener('click', handler);
    return button;
  }

  function buildPanel() {
    var style = document.createElement('style');
    style.textContent = STYLE;
    document.head.appendChild(style);

    panel = document.createElement('div');
    panel.id = 'wbt-tools';
    panel.setAttribute('role', 'group');
    panel.setAttribute('aria-label', '配置导入与保存');
    panel.appendChild(makeButton('导入配置', ICON_IMPORT, pickFile));
    panel.appendChild(makeButton('保存配置', ICON_EXPORT, saveConfig));
    document.body.appendChild(panel);
  }

  // 贴在左下角「工作区」按钮正上方，宽度与侧边栏一致；侧边栏收起时只留图标。
  // 这两个按钮只服务训练工作台：其它页面没有参数表单，显示出来只会让人误会。
  function onWorkbenchPage() {
    var path = location.pathname.replace(/\/+$/, '');
    return path === '/train' || path === '';
  }

  function positionPanel() {
    if (!panel) return;
    panel.style.display = onWorkbenchPage() ? '' : 'none';
    if (!onWorkbenchPage()) return;
    var anchor = document.querySelector('.account-wrap') || document.querySelector('.account-trigger');
    if (!anchor) return;
    var rect = anchor.getBoundingClientRect();
    if (!rect.width) return;
    panel.style.left = rect.left + 'px';
    panel.style.width = rect.width + 'px';
    panel.style.bottom = window.innerHeight - rect.top + 6 + 'px';
    panel.classList.toggle('is-compact', rect.width < 120);
  }

  function watchLayout() {
    var scheduled = false;
    var schedule = function () {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(function () {
        scheduled = false;
        positionPanel();
      });
    };
    window.addEventListener('resize', schedule);
    window.addEventListener('scroll', schedule, true);
    new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
    setInterval(schedule, 1000);
    schedule();
  }

  function start() {
    if (document.getElementById('wbt-tools')) return;
    buildPanel();
    watchLayout();
    flushToast();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
