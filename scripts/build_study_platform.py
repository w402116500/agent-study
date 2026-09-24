from run_temp import html_template
import sys, os, json, re
sys.stdout.reconfigure(encoding='utf-8')

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT_DIR, 'scripts'))
import parse_test as pt

# 1. Parse all questions
questions = pt.parse_all_questions()

for q in questions:
    if 'question' not in q or not q['question']:
        q['question'] = q['title']
    if 'sourcePaths' not in q or not q['sourcePaths']:
        q['sourcePaths'] = [q['mdPath']]
    if 'sourceLabels' not in q or not q['sourceLabels']:
        q['sourceLabels'] = [q['moduleShort'], q['project']]
    if 'confidence' not in q or not q['confidence']:
        q['confidence'] = '实测对账' if q['module'].startswith(('06', '07', '08')) else '权威八股'

print(f"Total questions: {len(questions)}")

# 2. Read CSS
with open(os.path.join(ROOT_DIR, 'scripts', 'full_style.css'), 'r', encoding='utf-8') as f:
    full_css = f.read()

# 3. Read prefix_js
with open(os.path.join(ROOT_DIR, 'scripts', 'prefix_js.js'), 'r', encoding='utf-8') as f:
    prefix_js = f.read()

# Enhance prefix_js with image rendering in formatRichText if not present
img_support_code = """
      // Check for markdown image: ![alt](url)
      const imgMatch = line.match(/^!\\[(.*?)\\]\\((.*?)\\)$/);
      if (imgMatch) {
        closeUl();
        closeStepGroup();
        const rel = resolveMediaRel(imgMatch[2]);
        const src = resolveMediaUrl(imgMatch[2]);
        html += '<div class="diagram-img-box"><img src="' + src + '" data-rel="' + escapeHtml(rel) + '" data-cdn-try="0" alt="' + escapeHtml(imgMatch[1]) + '" loading="lazy" decoding="async" onerror="window.__onStudyImgError && window.__onStudyImgError(this)">' + (imgMatch[1] ? '<div style="font-size:12px;color:var(--text-muted);margin-top:6px;">' + escapeHtml(imgMatch[1]) + '</div>' : '') + '</div>';
        continue;
      }
"""

if 'diagram-img-box' not in prefix_js:
    prefix_js = prefix_js.replace(
        "      // Normal paragraph",
        img_support_code + "\n      // Normal paragraph"
    )

# Now craft enhanced suffix_js
suffix_js = """
  // State keys
  const RECITATION_KEY = 'project-interview-study-recitation-v1';
  state.recitationMode = readBool(RECITATION_KEY, false);
  state.revealed = false;
  state.module = 'ALL';

  function saveRecitation() {
    try {
      localStorage.setItem(RECITATION_KEY, state.recitationMode ? '1' : '0');
    } catch (_) {}
  }

  function updateRecitationUI() {
    const btn = $('recitationToggleBtn');
    if (btn) {
      if (state.recitationMode) {
        btn.classList.add('active');
        btn.innerHTML = '<span>🎯 背诵自测中</span> <span class="kbd-tag">M</span>';
      } else {
        btn.classList.remove('active');
        btn.innerHTML = '<span>🎯 背诵自测模式</span> <span class="kbd-tag">M</span>';
      }
    }
  }

  window.toggleRecitationMode = function() {
    state.recitationMode = !state.recitationMode;
    state.revealed = false;
    saveRecitation();
    updateRecitationUI();
    renderCard(currentList());
    showToast(state.recitationMode ? '已开启背诵自测模式（答案已遮罩）' : '已退出背诵模式', '🎯');
  };

  window.revealAnswer = function() {
    state.revealed = true;
    const wrapper = document.querySelector('.answer-sections-wrapper');
    if (wrapper) wrapper.classList.add('revealed');
    const overlay = document.querySelector('.recitation-overlay');
    if (overlay) overlay.style.display = 'none';
    showToast('标准答案已揭晓', '👁️');
  };

  function filtered() {
    const q = state.query.trim().toLowerCase();
    return QUESTIONS.filter(item => {
      const matchText = !q || [item.id, item.title, item.question, item.oneLiner, item.answer30, item.answer120, item.moduleName, ...(item.topics || [])].join(' ').toLowerCase().includes(q);
      
      let matchProject = true;
      if (state.project !== 'ALL') {
        if (state.project === 'SuperMew') {
          matchProject = item.project === 'SuperMew' || item.module === '06_SuperMew项目深挖';
        } else if (state.project === 'DataPilot') {
          matchProject = item.project === 'DataPilot' || item.module === '07_DataPilot项目深挖';
        } else if (state.project === 'ARCH') {
          matchProject = item.module === '08_项目架构与综合追问' || item.project === '两个项目通用' || item.tag === 'ARCH';
        } else if (state.project === 'GENERIC') {
          matchProject = item.project === '通用基础' || item.tag === 'GENERIC';
        } else {
          matchProject = item.project === state.project;
        }
      }

      const matchModule = state.module === 'ALL' || item.module === state.module;
      const matchTopic = state.topic === 'ALL' || (item.topics || []).includes(state.topic);
      const matchType = state.type === 'ALL' || item.type === state.type;
      const matchStatus = state.statusFilter === 'ALL' || statusOf(item.id) === state.statusFilter;

      return matchText && matchProject && matchModule && matchTopic && matchType && matchStatus;
    });
  }

  function currentList() {
    const list = filtered();
    if (!list.length) return list;
    if (!list.some(x => x.id === state.currentId)) state.currentId = list[0].id;
    return list;
  }

  function renderStats(list) {
    const counts = QUESTIONS.reduce((acc, item) => {
      const st = statusOf(item.id);
      acc[st] = (acc[st] || 0) + 1;
      return acc;
    }, {});
    
    const mastered = counts.mastered || 0;
    const review = (counts.review || 0) + (counts.fuzzy || 0);
    const total = QUESTIONS.length;
    const pct = ((mastered / total) * 100).toFixed(1);

    $('totalCount').textContent = total;
    $('masteredCount').textContent = mastered;
    $('reviewCount').textContent = review;
    $('visibleCount').textContent = list.length;
    $('listCountSpan').textContent = list.length + ' / ' + total + ' 题';

    $('progressFill').style.width = pct + '%';
    $('progressLabel').textContent = '掌握率 ' + pct + '% (' + mastered + ' / ' + total + ')';

    const labels = [];
    if (state.project !== 'ALL') labels.push(state.project === 'ARCH' ? '架构综合' : state.project === 'GENERIC' ? '通用八股' : state.project);
    if (state.module !== 'ALL') labels.push(state.module.split('_')[1] || state.module);
    if (state.topic !== 'ALL') labels.push(state.topic);
    if (state.type !== 'ALL') labels.push(state.type);
    if (state.statusFilter !== 'ALL') labels.push({ unmarked: '未标记', mastered: '已掌握', fuzzy: '模糊', review: '待复习' }[state.statusFilter] || state.statusFilter);
    if (state.query) labels.push('"' + state.query + '"');
    
    $('filterSummary').textContent = '当前筛选：' + (labels.length ? labels.join(' · ') : '全部题目');
    updateRecitationUI();
  }

  function renderList(list) {
    const container = $('resultList');
    if (!list.length) {
      container.innerHTML = '<div style="padding:18px;text-align:center;color:var(--text-muted);font-size:12px">未找到匹配题目</div>';
      return;
    }
    container.innerHTML = list.map(item => {
      const st = statusOf(item.id);
      const isActive = item.id === state.currentId;
      return '<button class="q-item ' + (isActive ? 'active' : '') + '" data-id="' + item.id + '">' +
        '<span class="q-status-dot ' + st + '"></span>' +
        '<span class="q-id-pill">' + item.id + '</span>' +
        '<span class="q-title-snippet">' + item.question + '</span>' +
      '</button>';
    }).join('');

    container.querySelectorAll('[data-id]').forEach(btn => {
      btn.addEventListener('click', () => {
        state.currentId = btn.dataset.id;
        state.revealed = false;
        render();
        btn.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        closeDrawer();
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });
    });
  }

  function renderCard(list) {
    const item = list.find(x => x.id === state.currentId);
    if (!item) {
      $('cardMount').innerHTML = '<div class="empty-card">' +
        '<h2>未找到匹配题目</h2>' +
        '<p>请尝试清空筛选条件或更换搜索关键词。</p>' +
        '<button class="btn btn-primary" style="margin-top:14px" onclick="document.getElementById(\\'clearBtn\\').click()">重置全部筛选</button>' +
      '</div>';
      $('positionLabel').textContent = '第 0 题';
      $('statusLabel').textContent = '—';
      $('statusLabel').className = 'status-pill-badge unmarked';
      return;
    }

    const index = list.findIndex(x => x.id === item.id);
    const st = statusOf(item.id);
    $('positionLabel').textContent = '第 ' + (index + 1) + ' / ' + list.length + ' 题';
    
    const stLabelMap = { unmarked: '未标记', mastered: '已掌握', fuzzy: '模糊', review: '待复习' };
    $('statusLabel').textContent = stLabelMap[st] || '未标记';
    $('statusLabel').className = 'status-pill-badge ' + st;

    const isOpen = state.allSectionsExpanded ? 'open' : '';
    const answerClass = state.answerVisible ? '' : 'hidden';

    const isRecitation = state.recitationMode;
    const isRevealed = state.revealed;
    const maskedClass = isRecitation ? ('recitation-masked' + (isRevealed ? ' revealed' : '')) : '';

    let overlayHtml = '';
    if (isRecitation && !isRevealed) {
      overlayHtml = '<div class="recitation-overlay" onclick="revealAnswer()">' +
        '<div class="recitation-hint-badge">' +
          '<span>🎯 点击揭晓攻防标准应答</span>' +
          '<span class="kbd-tag">Space</span>' +
        '</div>' +
      '</div>';
    }

    // Keypoints HTML
    const keyPointsHtml = (item.keyPoints || []).map(kp => '<li><span class="check-icon">✓</span><div>' + formatRichText(kp) + '</div></li>').join('');
    
    // Follow-ups HTML
    const followUpsHtml = (item.followUps || []).map(fu => renderFollowUpItem(fu)).join('');

    // Boundaries HTML
    const boundariesHtml = (item.boundaries || []).map(b => '<li><span class="warn-icon">⚠️</span><div>' + formatRichText(b) + '</div></li>').join('');

    // Paths HTML
    const pathsHtml = (item.sourcePaths || []).map((p, pIdx) => '<div class="path-code-chip" onclick="copyPath(' + pIdx + ')"><span>' + p + '</span><span style="font-size:10px;color:var(--text-light)">复制</span></div>').join('');

    // Docsify link
    const docsifyUrl = 'index.html#/' + encodeURI(item.mdPath);

    $('cardMount').innerHTML =
      '<article class="study-card">' +
        '<div class="card-meta-bar">' +
          '<div class="meta-left">' +
            '<span class="badge-id">' + item.id + '</span>' +
            '<span class="badge-project ' + item.project + '">' + item.project + '</span>' +
            '<span class="badge-module">' + (item.moduleShort || item.module) + '</span>' +
            '<span class="badge-diff ' + (item.difficulty || '基础') + '">' + (item.difficulty || '基础') + '</span>' +
            '<span class="badge-type">' + item.type + '</span>' +
          '</div>' +
          '<div class="meta-right">' +
            (item.topics || []).map(t => '<span class="badge-topic"># ' + t + '</span>').join('') +
            '<span class="badge-confidence">🛡️ ' + item.confidence + '</span>' +
            '<a href="' + docsifyUrl + '" target="_blank" class="btn-docsify-link" title="在 Docsify 知识库中查看完整 Markdown 原文"><span>📖 Docsify 原文 ↗</span></a>' +
          '</div>' +
        '</div>' +

        '<div class="question-container">' +
          '<h2 class="question-title">' + item.question + '</h2>' +
          '<button class="copy-q-btn" onclick="copyQuestionText(this)">📋 复制题目</button>' +
        '</div>' +

        '<div class="oneliner-box">' +
          '<div class="oneliner-icon">💡</div>' +
          '<div class="oneliner-content">' +
            '<div class="oneliner-tag">一句话速记结论</div>' +
            '<div class="oneliner-text">' + formatRichText(item.oneLiner) + '</div>' +
          '</div>' +
        '</div>' +

        '<div class="answer-panel-header">' +
          '<h3>📚 面试应答卡（分层解析）</h3>' +
          '<div style="display:flex;gap:8px">' +
            '<button class="btn btn-sm" id="toggleAnswerBtn">' + (state.answerVisible ? '隐藏全部答案' : '展开答案') + '</button>' +
          '</div>' +
        '</div>' +

        '<div class="answer-sections-wrapper ' + answerClass + ' ' + maskedClass + '">' +
          overlayHtml +
          
          '<!-- 30s verbal answer -->' +
          '<details class="study-section section-30s" ' + isOpen + '>' +
            '<summary class="section-summary">' +
              '<span class="summary-title">🎙️ 30 秒高频口答精要（直击要害 / 电梯演讲）</span>' +
              '<span class="summary-actions">' +
                '<span class="char-badge">' + ((item.answer30 || '').length) + ' 字</span>' +
                '<button class="copy-section-btn" onclick="event.stopPropagation(); copyCurrentAnswer(this, 30)">复制口答</button>' +
              '</span>' +
            '</summary>' +
            '<div class="section-content" style="background:#fbfcfe">' +
              formatRichText(item.answer30) +
            '</div>' +
          '</details>' +

          '<!-- 60-120s deep dive answer -->' +
          '<details class="study-section" ' + isOpen + '>' +
            '<summary class="section-summary">' +
              '<span class="summary-title">🧭 60–120 秒深度展开（系统架构 / 机制与推演）</span>' +
              '<span class="summary-actions">' +
                '<span class="char-badge">' + ((item.answer120 || '').length) + ' 字</span>' +
                '<button class="copy-section-btn" onclick="event.stopPropagation(); copyCurrentAnswer(this, 120)">复制详答</button>' +
              '</span>' +
            '</summary>' +
            '<div class="section-content">' +
              formatRichText(item.answer120) +
            '</div>' +
          '</details>' +

          (keyPointsHtml ? (
            '<details class="study-section" ' + isOpen + '>' +
              '<summary class="section-summary">' +
                '<span class="summary-title">⭐ 核心关键技术点（回答骨架）</span>' +
              '</summary>' +
              '<div class="section-content">' +
                '<ul class="keypoints-list">' + keyPointsHtml + '</ul>' +
              '</div>' +
            '</details>'
          ) : '') +

          (followUpsHtml ? (
            '<details class="study-section" ' + isOpen + '>' +
              '<summary class="section-summary">' +
                '<span class="summary-title">❓ 面试官高频追问预判（连环问攻防）</span>' +
              '</summary>' +
              '<div class="section-content">' +
                '<ul class="followups-list">' + followUpsHtml + '</ul>' +
              '</div>' +
            '</details>'
          ) : '') +

          (boundariesHtml ? (
            '<details class="study-section" ' + isOpen + '>' +
              '<summary class="section-summary">' +
                '<span class="summary-title">⚠️ 失败边界与防坑要点（切忌说错的红线）</span>' +
              '</summary>' +
              '<div class="section-content">' +
                '<ul class="boundaries-list">' + boundariesHtml + '</ul>' +
              '</div>' +
            '</details>'
          ) : '') +
        '</div>' +

        '<!-- Meta Details Grid -->' +
        '<div class="source-details-grid">' +
          '<div class="meta-info-card">' +
            '<h4>来源与可信度分层</h4>' +
            '<div class="tag-container">' +
              (item.sourceLabels || []).map(lbl => '<span class="source-chip" style="background:#eff6ff;color:#1d4ed8;border-color:#bfdbfe">' + lbl + '</span>').join('') +
              '<span class="source-chip">' + (item.tag === 'DATAPILOT' || item.tag === 'SUPERMEW' ? '真实源码对账' : '技术深挖标准') + '</span>' +
            '</div>' +
          '</div>' +
          
          '<div class="meta-info-card">' +
            '<h4>文档站映射</h4>' +
            '<div class="tag-container">' +
              '<span class="source-chip" style="font-family:var(--font-mono);font-size:11px">' + item.mdPath + '</span>' +
            '</div>' +
            '<p style="margin-top:6px;font-size:11px;color:var(--text-light)">点击右上角「📖 Docsify 原文 ↗」可直达知识库对应 Markdown 篇章进行全景研读。</p>' +
          '</div>' +
        '</div>' +

        '<!-- Source paths -->' +
        '<div class="paths-section">' +
          '<h4>📂 本地源码、复习手册与证据链路径</h4>' +
          '<div class="paths-list">' + pathsHtml + '</div>' +
        '</div>' +

        '<!-- Action Bar -->' +
        '<div class="card-actions-bar">' +
          '<div class="status-btn-group">' +
            '<button class="status-action-btn ' + (st === 'mastered' ? 'active mastered' : '') + '" data-status="mastered">' +
              '<span>✓ 已掌握</span> <span class="kbd-tag">1</span>' +
            '</button>' +
            '<button class="status-action-btn ' + (st === 'fuzzy' ? 'active fuzzy' : '') + '" data-status="fuzzy">' +
              '<span>≈ 模糊</span> <span class="kbd-tag">2</span>' +
            '</button>' +
            '<button class="status-action-btn ' + (st === 'review' ? 'active review' : '') + '" data-status="review">' +
              '<span>↻ 待复习</span> <span class="kbd-tag">3</span>' +
            '</button>' +
          '</div>' +
          
          '<div class="nav-btn-group">' +
            '<button class="btn" id="cardPrevBtn">← 上一题</button>' +
            '<button class="btn btn-primary" id="cardNextBtn">下一题 →</button>' +
          '</div>' +
        '</div>' +
      '</article>';

    // Event listeners inside card
    $('toggleAnswerBtn').addEventListener('click', () => {
      state.answerVisible = !state.answerVisible;
      save();
      renderCard(currentList());
    });

    $('cardMount').querySelectorAll('[data-status]').forEach(btn => {
      btn.addEventListener('click', () => {
        statuses[item.id] = btn.dataset.status;
        save();
        render();
      });
    });

    $('cardPrevBtn').addEventListener('click', () => move(-1));
    $('cardNextBtn').addEventListener('click', () => move(1));
  }

  function move(delta) {
    const list = currentList();
    if (!list.length) return;
    const i = list.findIndex(x => x.id === state.currentId);
    state.currentId = list[(i + delta + list.length) % list.length].id;
    state.revealed = false;
    render();
    setTimeout(() => {
      const activeBtn = $('resultList').querySelector('.q-item.active');
      if (activeBtn) activeBtn.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }, 50);
  }

  function randomQuestion() {
    const list = currentList();
    if (!list.length) return;
    const rand = list[Math.floor(Math.random() * list.length)];
    state.currentId = rand.id;
    state.revealed = false;
    render();
    setTimeout(() => {
      const activeBtn = $('resultList').querySelector('.q-item.active');
      if (activeBtn) activeBtn.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }, 50);
  }

  function render() {
    const list = currentList();
    renderStats(list);
    renderList(list);
    renderCard(list);
  }

  // Inputs
  $('search').addEventListener('input', e => { state.query = e.target.value; render(); });
  [['project','project'], ['moduleFilter','module'], ['topic','topic'], ['type','type'], ['statusFilter','statusFilter']].forEach(([id, key]) => {
    $(id).addEventListener('change', e => { state[key] = e.target.value; render(); });
  });

  // Buttons
  $('randomBtn').addEventListener('click', randomQuestion);
  $('prevBtn').addEventListener('click', () => move(-1));
  $('nextBtn').addEventListener('click', () => move(1));

  // Mobile Drawer Controls
  function openDrawer() {
    const sidebar = $('sidebarNav');
    const backdrop = $('drawerBackdrop');
    if (sidebar) sidebar.classList.add('drawer-open');
    if (backdrop) backdrop.classList.add('active');
    document.body.style.overflow = 'hidden';
  }

  function closeDrawer() {
    const sidebar = $('sidebarNav');
    const backdrop = $('drawerBackdrop');
    if (sidebar) sidebar.classList.remove('drawer-open');
    if (backdrop) backdrop.classList.remove('active');
    document.body.style.overflow = '';
  }

  const mobileMenuBtn = $('mobileMenuBtn');
  if (mobileMenuBtn) mobileMenuBtn.addEventListener('click', openDrawer);

  const mobileCloseBtn = $('mobileCloseBtn');
  if (mobileCloseBtn) mobileCloseBtn.addEventListener('click', closeDrawer);

  const drawerBackdrop = $('drawerBackdrop');
  if (drawerBackdrop) drawerBackdrop.addEventListener('click', closeDrawer);

  // Mobile Bottom Bar Navigation
  const mNavMenuBtn = $('mNavMenuBtn');
  if (mNavMenuBtn) mNavMenuBtn.addEventListener('click', openDrawer);

  const mNavPrevBtn = $('mNavPrevBtn');
  if (mNavPrevBtn) mNavPrevBtn.addEventListener('click', () => { move(-1); window.scrollTo({ top: 0, behavior: 'smooth' }); });

  const mNavNextBtn = $('mNavNextBtn');
  if (mNavNextBtn) mNavNextBtn.addEventListener('click', () => { move(1); window.scrollTo({ top: 0, behavior: 'smooth' }); });

  const mNavRandomBtn = $('mNavRandomBtn');
  if (mNavRandomBtn) mNavRandomBtn.addEventListener('click', () => { randomQuestion(); window.scrollTo({ top: 0, behavior: 'smooth' }); });

  $('clearBtn').addEventListener('click', () => {
    state.query = '';
    state.project = 'ALL';
    state.module = 'ALL';
    state.topic = 'ALL';
    state.type = 'ALL';
    state.statusFilter = 'ALL';
    $('search').value = '';
    $('project').value = 'ALL';
    $('moduleFilter').value = 'ALL';
    $('topic').value = 'ALL';
    $('type').value = 'ALL';
    $('statusFilter').value = 'ALL';
    render();
  });

  $('toggleAllSectionsBtn').addEventListener('click', () => {
    state.allSectionsExpanded = !state.allSectionsExpanded;
    $('toggleAllSectionsBtn').innerHTML = state.allSectionsExpanded ? '<span>📖 全展开</span>' : '<span>📁 全折叠</span>';
    const sections = $('cardMount').querySelectorAll('.study-section');
    sections.forEach(s => {
      if (state.allSectionsExpanded) s.setAttribute('open', '');
      else s.removeAttribute('open');
    });
  });

  // Keyboard navigation
  document.addEventListener('keydown', e => {
    if (e.target.matches('input, select, textarea')) {
      if (e.key === 'Escape') e.target.blur();
      return;
    }
    const key = e.key.toLowerCase();
    if (e.key === '/') {
      e.preventDefault();
      $('search').focus();
    } else if (key === 'j' || e.key === 'ArrowRight') {
      move(1);
    } else if (key === 'k' || e.key === 'ArrowLeft') {
      move(-1);
    } else if (key === 'r') {
      randomQuestion();
    } else if (key === 'm') {
      toggleRecitationMode();
    } else if (e.code === 'Space') {
      e.preventDefault();
      if (state.recitationMode && !state.revealed) {
        revealAnswer();
      } else {
        state.answerVisible = !state.answerVisible;
        save();
        renderCard(currentList());
      }
    } else if (key === '1') {
      if (state.currentId) { statuses[state.currentId] = 'mastered'; save(); render(); }
    } else if (key === '2') {
      if (state.currentId) { statuses[state.currentId] = 'fuzzy'; save(); render(); }
    } else if (key === '3') {
      if (state.currentId) { statuses[state.currentId] = 'review'; save(); render(); }
    } else if (key === '0') {
      if (state.currentId) { statuses[state.currentId] = 'unmarked'; save(); render(); }
    }
  });

  render();
})();
"""

full_script = prefix_js + "\n\n" + suffix_js
full_html = html_template + full_script + "\n</script>\n</body>\n</html>"

output_path = os.path.join(ROOT_DIR, 'study.html')
with open(output_path, 'w', encoding='utf-8') as out_f:
    out_f.write(full_html)

print(f"Successfully generated study.html! File size: {os.path.getsize(output_path):,} bytes")
