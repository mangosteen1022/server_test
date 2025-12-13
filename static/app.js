/* Email Accounts Manager - Main Application */

// ==================== Global State ====================
const AppState = {
    selectedAccountId: null,
    selectedMailId: null,
    selectedAccountIds: new Set(),
    accounts: [],
    mails: [],
    // 账号分页参数
    accountCurrentPage: 1,
    accountPageSize: 50,
    accountTotalPages: 0,
    accountTotalCount: 0,
    // 邮件分页参数
    mailCurrentPage: 1,
    mailPageSize: 50,
    mailTotalPages: 0,
    mailTotalCount: 0,
    // 其他参数
    isResizing: false,
    leftPanelWidth: 350,
    currentTheme: 'default',
    mailTab: 'current' // 'current' or 'search'
};

// ==================== API Configuration ====================
const API_BASE = ''; // 回到根路径访问API
const originalFetch = window.fetch;
window.fetch = async function(url, options = {}) {
    // 1. 自动添加 Authorization Header
    const token = localStorage.getItem('token');
    if (token) {
        options.headers = options.headers || {};
        // 确保 headers 是对象
        if (options.headers instanceof Headers) {
            options.headers.append('Authorization', `Bearer ${token}`);
        } else {
            options.headers['Authorization'] = `Bearer ${token}`;
        }
    }

    // 2. 发送请求
    try {
        const response = await originalFetch(url, options);

        // 3. 拦截 401 (未授权/Token过期)
        if (response.status === 401) {
            console.warn('Token expired or invalid, redirecting to login...');
            localStorage.removeItem('token'); // 清除失效 Token
            window.location.href = '/login.html';
            return response; // 或者抛出错误
        }

        return response;
    } catch (error) {
        throw error;
    }
};
const api = {
    // 账号相关API
    accounts: {
        list: (params = {}) => {
            const query = new URLSearchParams(params);
            return fetch(`${API_BASE}/accounts?${query}`).then(r => r.json());
        },

        get: (id) => {
            return fetch(`${API_BASE}/accounts/${id}`).then(r => r.json());
        },

        create: (data) => {
            return fetch(`${API_BASE}/accounts/batch`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify([data])
            }).then(r => r.json());
        },

        update: (id, data) => {
            return fetch(`${API_BASE}/accounts/${id}`, {
                method: 'PATCH',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            }).then(r => r.json());
        },

        delete: (id) => {
            return fetch(`${API_BASE}/accounts/${id}`, {
                method: 'DELETE'
            }).then(r => r.json());
        },

        getHistory: (accountId, params = {}) => {
            // 先获取账号信息以获得 group_id
            return api.accounts.get(accountId).then(account => {
                if (account && account.group_id) {
                    const query = new URLSearchParams(params);
                    return fetch(`${API_BASE}/accounts/history/${account.group_id}?${query}`).then(r => r.json());
                } else {
                    throw new Error('账号信息不存在或没有 group_id');
                }
            });
        },

        restore: (id, data) => {
            return fetch(`${API_BASE}/accounts/${id}/restore`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            }).then(r => r.json());
        }
    },

    // OAuth相关API
    oauth: {
        getAuthUrl: (tokenUuid) => {
            const url = tokenUuid ?
                `${API_BASE}/oauth/url?token_uuid=${tokenUuid}` :
                `${API_BASE}/oauth/url`;
            return fetch(url).then(r => r.json());
        },

        handleResponse: (responseUrl, tokenUuid) => {
            const url = tokenUuid ?
                `${API_BASE}/oauth/handle-response?token_uuid=${tokenUuid}` :
                `${API_BASE}/oauth/handle-response`;
            return fetch(url, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({response_url: responseUrl})
            }).then(r => r.json());
        },

        login: (loginData) => {
            return fetch(`${API_BASE}/oauth/login`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(loginData)
            }).then(r => r.json());
        },

        getUserInfo: (tokenUuid) => {
            return fetch(`${API_BASE}/oauth/me?token_uuid=${tokenUuid}`).then(r => r.json());
        },

        getFolders: (tokenUuid) => {
            return fetch(`${API_BASE}/oauth/folders?token_uuid=${tokenUuid}`).then(r => r.json());
        },

        logout: (tokenUuid) => {
            return fetch(`${API_BASE}/oauth/logout?token_uuid=${tokenUuid}`, {
                method: 'POST'
            }).then(r => r.json());
        },

        checkToken: (tokenUuid) => {
            return fetch(`${API_BASE}/oauth/check-token?token_uuid=${tokenUuid}`).then(r => r.json());
        }
    },

    // 批量认证API
    auth: {
        batchLogin: (groupIds) => {
            // 直接使用group_id
            return fetch(`${API_BASE}/auth/login/groups`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({group_ids: groupIds})
            }).then(r => r.json());
        },

        getLoginStatus: (taskId) => {
            return fetch(`${API_BASE}/auth/login/status/${taskId}`).then(r => r.json());
        },

        getAccountLoginStatus: (groupId) => {
            // 获取该组的登录任务状态
            return fetch(`${API_BASE}/auth/login/status/${groupId}`).then(r => r.json());
        },

        batchSync: (groupIds, strategy = 'auto') => {
            // 直接使用group_id
            return fetch(`${API_BASE}/auth/sync/groups`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    group_ids: groupIds,
                    strategy: strategy
                })
            }).then(r => r.json());
        },

        getSyncStatus: (taskId) => {
            return fetch(`${API_BASE}/auth/sync/status/${taskId}`).then(r => r.json());
        },

        verifyToken: (groupId) => {
            // 直接使用group_id
            return fetch(`${API_BASE}/auth/token/verify/${groupId}`).then(r => r.json());
        }
    },

        // 邮件同步API
        sync: {
            syncAccount: (accountId, strategy = 'auto') => {
                // 先获取账号的group_id，然后使用v2 API
                return api.accounts.get(accountId).then(account => {
                    if (account && account.group_id) {
                        return fetch(`${API_BASE}/auth/sync/groups`, {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({
                                group_ids: [account.group_id],
                                strategy: strategy
                            })
                        }).then(r => r.json());
                    } else {
                        throw new Error('账号信息不存在或没有 group_id');
                    }
                });
            },

            getSyncStatus: (taskId) => {
                // 使用v2 API查询任务状态
                return fetch(`${API_BASE}/auth/sync/status/${taskId}`).then(r => r.json());
            },

            getMessages: (tokenUuid, params = {}) => {
                const url = new URL(`${API_BASE}/sync/messages`);
                url.searchParams.set('token_uuid', tokenUuid);
                Object.keys(params).forEach(key => {
                    if (params[key] !== undefined) {
                        url.searchParams.set(key, params[key]);
                    }
                });
                return fetch(url).then(r => r.json());
            },

            getDelta: (tokenUuid, deltaLink, folderId) => {
                const url = new URL(`${API_BASE}/sync/delta`);
                url.searchParams.set('token_uuid', tokenUuid);
                if (deltaLink) url.searchParams.set('delta_link', deltaLink);
                if (folderId) url.searchParams.set('folder_id', folderId);
                return fetch(url).then(r => r.json());
            },

            getUnread: (tokenUuid, folderId, top = 25) => {
                const url = new URL(`${API_BASE}/sync/unread`);
                url.searchParams.set('token_uuid', tokenUuid);
                if (folderId) url.searchParams.set('folder_id', folderId);
                url.searchParams.set('top', top);
                return fetch(url).then(r => r.json());
            },

            getRecent: (tokenUuid, days = 7, folderId, top = 25) => {
                const url = new URL(`${API_BASE}/sync/recent`);
                url.searchParams.set('token_uuid', tokenUuid);
                url.searchParams.set('days', days);
                if (folderId) url.searchParams.set('folder_id', folderId);
                url.searchParams.set('top', top);
                return fetch(url).then(r => r.json());
            }
        },

        // 邮件管理API
        mails: {
            list: (accountId, params = {}) => {
                const query = new URLSearchParams(params);
                return fetch(`${API_BASE}/mail/accounts/${accountId}/mails?${query}`).then(r => r.json());
            },

            get: (messageId) => {
                return fetch(`${API_BASE}/mail/${messageId}`).then(r => r.json());
            },

            getPreview: (messageId) => {
                return fetch(`${API_BASE}/mail/${messageId}/preview`).then(r => r.json());
            },

            create: (data) => {
                return fetch(`${API_BASE}/mail/messages`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(data)
                }).then(r => r.json());
            },

            update: (messageId, data) => {
                return fetch(`${API_BASE}/mail/${messageId}`, {
                    method: 'PATCH',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(data)
                }).then(r => r.json());
            },

            delete: (messageId) => {
                return fetch(`${API_BASE}/mail/${messageId}`, {
                    method: 'DELETE'
                }).then(r => r.json());
            },

            search: (data) => {
                return fetch(`${API_BASE}/mail/search`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(data)
                }).then(r => r.json());
            },

            getStatistics: (accountId) => {
                return fetch(`${API_BASE}/mail/statistics/${accountId}`).then(r => r.json());
            },

            detail: (messageId) => {
                return fetch(`${API_BASE}/mail/${messageId}`).then(r => r.json());
            },

            download: (messageId) => {
                return fetch(`${API_BASE}/mail/${messageId}/download`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'}
                }).then(r => r.json());
            }
        },

        // 文件夹管理API
        folders: {
            list: (accountId) => {
                return fetch(`${API_BASE}/folders/accounts/${accountId}/folders`).then(r => r.json());
            },

            sync: (accountId, folders) => {
                return fetch(`${API_BASE}/folders/accounts/${accountId}/folders/sync`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(folders)
                }).then(r => r.json());
            },

            resolve: (accountIds) => {
                const query = accountIds.join(',');
                return fetch(`${API_BASE}/folders/resolve?account_ids=${query}`).then(r => r.json());
            }
        }
};

// ==================== DOM Elements ====================
const elements = {
    // Header
    searchField: document.getElementById('searchField'),
    searchInput: document.getElementById('searchInput'),
    themeSelector: document.getElementById('themeSelector'),
    addAccountBtn: document.getElementById('addAccountBtn'),
    settingsBtn: document.getElementById('settingsBtn'),

    // Layout
    leftPanel: document.querySelector('.left-panel'),
    resizer: document.getElementById('resizer'),
    rightPanel: document.querySelector('.right-panel'),

    // Accounts
    accountsTableBody: document.getElementById('accountsTableBody'),
    selectAllAccounts: document.getElementById('selectAllAccounts'),
    bulkActionsBar: document.getElementById('bulkActionsBar'),
    selectedCount: document.getElementById('selectedCount'),
    bulkDeleteBtn: document.getElementById('bulkDeleteBtn'),
    bulkNoteBtn: document.getElementById('bulkNoteBtn'),
    bulkLoginBtn: document.getElementById('bulkLoginBtn'),
    bulkSyncBtn: document.getElementById('bulkSyncBtn'),
    bulkNoteInput: document.getElementById('bulkNoteInput'),
    pageInfo: document.getElementById('pageInfo'),
    prevPageBtn: document.getElementById('prevPageBtn'),
    nextPageBtn: document.getElementById('nextPageBtn'),
    pageSizeSelect: document.getElementById('pageSizeSelect'),

    // Mails
    currentMailTab: document.getElementById('currentMailTab'),
    mailPageInfo: document.getElementById('mailPageInfo'),
    mailPrevPageBtn: document.getElementById('mailPrevPageBtn'),
    mailNextPageBtn: document.getElementById('mailNextPageBtn'),
    mailPageSizeSelect: document.getElementById('mailPageSizeSelect'),
    mailsTabs: document.querySelectorAll('.mails-tab'),
    mailSearchField: document.getElementById('mailSearchField'),
    mailSearch: document.getElementById('mailSearch'),
    composeBtn: document.querySelector('.compose-btn'),
    mailsListBody: document.getElementById('mailsListBody'),
    selectAllMails: document.getElementById('selectAllMails'),

    // Mail preview
    mailSubject: document.getElementById('mailSubject'),
    mailFrom: document.getElementById('mailFrom'),
    mailTo: document.getElementById('mailTo'),
    mailTime: document.getElementById('mailTime'),
    mailContent: document.getElementById('mailContent'),

    // Context menus
    accountContextMenu: document.getElementById('accountContextMenu'),
    mailContextMenu: document.getElementById('mailContextMenu')
};

// ==================== Theme Management ====================
function setTheme(theme) {
    AppState.currentTheme = theme;
    document.body.setAttribute('data-theme', theme);
    elements.themeSelector.value = theme;
    localStorage.setItem('theme', theme);
}

function initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'default';
    setTheme(savedTheme);
}

// ==================== Panel Resizing ====================
function initResizer() {
    const resizer = elements.resizer;
    const leftPanel = elements.leftPanel;
    const mainContainer = document.querySelector('.main-container');

    let isResizing = false;
    let startX = 0;
    let startWidth = 0;

    resizer.addEventListener('mousedown', (e) => {
        isResizing = true;
        startX = e.clientX;
        startWidth = leftPanel.offsetWidth;
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;

        const deltaX = e.clientX - startX;
        const newWidth = startWidth + deltaX;

        // 限制最小和最大宽度
        const minWidth = 250;
        const maxWidth = 600;

        if (newWidth >= minWidth && newWidth <= maxWidth) {
            leftPanel.style.width = `${newWidth}px`;
            AppState.leftPanelWidth = newWidth;
        }
    });

    document.addEventListener('mouseup', () => {
        if (isResizing) {
            isResizing = false;
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        }
    });
}

// ==================== Account Management ====================
async function loadAccounts(searchParams = {}) {
    try {
        elements.accountsTableBody.innerHTML = '<tr><td colspan="3" class="mail-placeholder">加载账号列表中...</td></tr>';

        const queryParams = {
            page: AppState.accountCurrentPage,
            size: AppState.accountPageSize,
            ...searchParams
        };

        console.log('Loading accounts with params:', queryParams);
        console.log('API URL:', `${API_BASE}/accounts?${new URLSearchParams(queryParams)}`);

        const response = await api.accounts.list(queryParams);

        console.log('Accounts API response:', response);

        AppState.accounts = response.items || [];
        AppState.accountTotalCount = response.total || 0;
        AppState.accountTotalPages = Math.ceil(AppState.accountTotalCount / AppState.accountPageSize);

        console.log('Processed accounts:', AppState.accounts);
        console.log('Total count:', AppState.totalCount);

        renderAccounts();
        updatePagination();
    } catch (error) {
        console.error('Failed to load accounts:', error);
        console.error('Error details:', {
            message: error.message,
            stack: error.stack,
            status: error.status,
            statusText: error.statusText
        });
        elements.accountsTableBody.innerHTML = `<tr><td colspan="3" class="mail-placeholder">加载账号列表失败: ${error.message}</td></tr>`;
    }
}

function renderAccounts() {
    const tbody = elements.accountsTableBody;

    if (AppState.accounts.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" class="mail-placeholder">暂无账号数据</td></tr>';
        return;
    }

    const accountsHtml = AppState.accounts.map((account, index) => {
        const rowClass = account.id === AppState.selectedAccountId ? 'account-row selected' : 'account-row';
        const isChecked = AppState.selectedAccountIds.has(account.id);
        return `
            <tr class="${rowClass}" data-account-id="${account.id}" data-status="${account.status || '未知'}">
                <td>
                    <input type="checkbox" class="account-checkbox account-select"
                           data-account-id="${account.id}" ${isChecked ? 'checked' : ''}>
                </td>
                <td>${AppState.accountCurrentPage * AppState.accountPageSize - AppState.accountPageSize + index + 1}</td>
                <td>${account.email}</td>
            </tr>
        `;
    }).join('');

    tbody.innerHTML = accountsHtml;

    // 添加事件监听
    tbody.querySelectorAll('.account-row').forEach(row => {
        row.addEventListener('click', (e) => {
            // 如果点击的是checkbox，不选中账号
            if (e.target.classList.contains('account-checkbox')) {
                return;
            }

            const accountId = parseInt(row.dataset.accountId);
            selectAccount(accountId);
        });

        // 复选框事件
        const checkbox = row.querySelector('.account-select');
        checkbox.addEventListener('change', (e) => {
            const accountId = parseInt(e.target.dataset.accountId);
            if (e.target.checked) {
                AppState.selectedAccountIds.add(accountId);
            } else {
                AppState.selectedAccountIds.delete(accountId);
            }
            updateBulkActionsBar();
        });

        // 右键菜单
        row.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            showAccountContextMenu(e, parseInt(row.dataset.accountId));
        });
    });

    // 全选复选框事件
    const selectAllCheckbox = document.getElementById('selectAllAccounts');
    selectAllCheckbox.addEventListener('change', (e) => {
        if (e.target.checked) {
            // 全选当前页的所有账号
            AppState.accounts.forEach(account => {
                AppState.selectedAccountIds.add(account.id);
            });
            tbody.querySelectorAll('.account-select').forEach(cb => {
                cb.checked = true;
            });
        } else {
            // 取消全选
            AppState.selectedAccountIds.clear();
            tbody.querySelectorAll('.account-select').forEach(cb => {
                cb.checked = false;
            });
        }
        updateBulkActionsBar();
    });

    updateBulkActionsBar();
}

function updatePagination() {
    const pageInfo = `第 ${AppState.accountCurrentPage}/${AppState.accountTotalPages} 页 (共${AppState.accountTotalCount}条)`;
    elements.pageInfo.textContent = AppState.accountTotalPages > 0 ? pageInfo : '第 0/0 页 (共0条)';

    elements.prevPageBtn.disabled = AppState.accountCurrentPage <= 1;
    elements.nextPageBtn.disabled = AppState.accountCurrentPage >= AppState.accountTotalPages;
}

function updateMailPagination() {
    const pageInfo = `第 ${AppState.mailCurrentPage}/${AppState.mailTotalPages} 页 (共${AppState.mailTotalCount}条)`;
    elements.mailPageInfo.textContent = AppState.mailTotalPages > 0 ? pageInfo : '第 0/0 页 (共0条)';

    elements.mailPrevPageBtn.disabled = AppState.mailCurrentPage <= 1;
    elements.mailNextPageBtn.disabled = AppState.mailCurrentPage >= AppState.mailTotalPages;
}

function updateBulkActionsBar() {
    const count = AppState.selectedAccountIds.size;
    const bulkBar = elements.bulkActionsBar;

    if (count > 0) {
        bulkBar.classList.remove('hidden');
        elements.selectedCount.textContent = count;

        // 启用/禁用批量操作按钮
        elements.bulkDeleteBtn.disabled = false;
        elements.bulkNoteBtn.disabled = false;
        elements.bulkLoginBtn.disabled = false;
        elements.bulkSyncBtn.disabled = false;
    } else {
        bulkBar.classList.add('hidden');
        elements.selectAllAccounts.checked = false;
    }
}

// 批量操作函数
async function bulkDeleteAccounts() {
    const count = AppState.selectedAccountIds.size;
    if (count === 0) return;

    if (confirm(`确定要删除选中的 ${count} 个账号吗？此操作不可撤销。`)) {
        try {
            const promises = Array.from(AppState.selectedAccountIds).map(id =>
                api.accounts.delete(id)
            );

            await Promise.all(promises);

            showToast(`成功删除 ${count} 个账号`, 'success');
            AppState.selectedAccountIds.clear();
            loadAccounts();
        } catch (error) {
            console.error('批量删除失败:', error);
            showToast('批量删除失败', 'error');
        }
    }
}

async function bulkUpdateNote() {
    const count = AppState.selectedAccountIds.size;
    if (count === 0) return;

    const note = elements.bulkNoteInput.value.trim();
    if (!note) {
        showToast('请输入批量备注内容', 'error');
        return;
    }

    try {
        const promises = Array.from(AppState.selectedAccountIds).map(id =>
            api.accounts.update(id, { note })
        );

        await Promise.all(promises);

        showToast(`成功为 ${count} 个账号添加备注`, 'success');
        elements.bulkNoteInput.value = '';
        AppState.selectedAccountIds.clear();
        loadAccounts();
    } catch (error) {
        console.error('批量备注失败:', error);
        showToast('批量备注失败', 'error');
    }
}

async function bulkLogin() {
    const count = AppState.selectedAccountIds.size;
    if (count === 0) return;

    try {
        // 获取选中的账号并提取唯一的group_id
        const accounts = Array.from(AppState.selectedAccountIds).map(id =>
            AppState.accounts.find(a => a.id === id)
        ).filter(Boolean);

        if (accounts.length === 0) {
            showToast('没有找到有效的账号数据', 'error');
            return;
        }

        // 提取唯一的group_id
        const groupIds = [...new Set(accounts.map(a => a.group_id).filter(Boolean))];

        if (groupIds.length === 0) {
            showToast('没有找到有效的组信息', 'error');
            return;
        }

        const response = await api.auth.batchLogin(groupIds);

        if (response.success) {
            showToast(`批量登录任务已提交，共${response.total_groups}个组`, 'success');
        } else {
            showToast(`批量登录失败: ${response.message || '未知错误'}`, 'error');
        }
    } catch (error) {
        console.error('批量登录失败:', error);
        showToast('批量登录失败', 'error');
    }
}

async function bulkSync() {
    const count = AppState.selectedAccountIds.size;
    if (count === 0) return;

    try {
        // 获取选中的账号并提取唯一的group_id
        const accounts = Array.from(AppState.selectedAccountIds).map(id =>
            AppState.accounts.find(a => a.id === id)
        ).filter(Boolean);

        if (accounts.length === 0) {
            showToast('没有找到有效的账号数据', 'error');
            return;
        }

        // 提取唯一的group_id
        const groupIds = [...new Set(accounts.map(a => a.group_id).filter(Boolean))];

        if (groupIds.length === 0) {
            showToast('没有找到有效的组信息', 'error');
            return;
        }

        const response = await api.auth.batchSync(groupIds);

        if (response.success) {
            showToast(`批量邮件同步任务已提交，共${response.total_groups}个组`, 'success');
        } else {
            showToast(`批量同步失败: ${response.message || '未知错误'}`, 'error');
        }
    } catch (error) {
        console.error('批量同步失败:', error);
        showToast('批量同步失败', 'error');
    }
}

function selectAccount(accountId) {
    AppState.selectedAccountId = accountId;

    // 更新UI
    document.querySelectorAll('.account-row').forEach(row => {
        row.classList.toggle('selected', parseInt(row.dataset.accountId) === accountId);
    });

    // 更新右侧tab显示当前选中的邮箱账号
    const account = AppState.accounts.find(a => a.id === accountId);
    if (account && elements.currentMailTab) {
        elements.currentMailTab.textContent = account.email;
    }

    // 加载账号邮件
    loadAccountMails(accountId);
}

async function syncAccount(accountId, strategy = 'auto') {
    try {
        const account = AppState.accounts.find(a => a.id === accountId);
        if (!account) return;

        const strategyNames = {
            'check': '检测邮件',
            'full': '完整同步',
            'recent': '按时间同步',
            'today': '同步今天邮件',
            'auto': '自动同步'
        };

        // 显示提示
        showToast(`开始${strategyNames[strategy]}...`, 'info');
        console.log(account)
        // 检查登录状态
        if (account.status !== '登录成功') {
            // 需要先登录
            showToast(`请先登录账号 ${account.email} 后���进行同步`, 'warning');
            return;
        }

        // 获取group_id
        if (!account.group_id) {
            showToast('账号没有group_id信息', 'error');
            return;
        }

        // 开始同步 - 使用group_id
        const response = await api.auth.batchSync([account.group_id], strategy);

        if (response.success) {
            showToast(`${strategyNames[strategy]}任务已提交`, 'success');
            // 可以添加轮询同步状态的逻辑
        } else {
            showToast(`${strategyNames[strategy]}失败: ${response.message}`, 'error');
        }
    } catch (error) {
        console.error('Failed to sync account:', error);
        showToast('同步失败', 'error');
    }
}

// ==================== Mail Management ====================
async function loadAccountMails(accountId, params = {}) {
    try {
        const tbody = elements.mailsListBody;
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 40px; color: var(--muted);">加载邮件中...</td></tr>';

        // 先检查API对象是否存在
        if (!api || !api.mails) {
            console.error('API or api.mails is undefined');
            tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 20px; color: var(--muted);">API未初始化</td></tr>';
            return;
        }

        console.log('API object exists, api.mails:', api.mails);
        console.log('Calling api.mails.list with accountId:', accountId);

        // 直接调用API
        const response = await api.mails.list(accountId, {
            page: AppState.mailCurrentPage,
            size: AppState.mailPageSize,
            ...params
        });

        console.log('Mails API response:', response);

        // 根据API文档，响应应该包含 items 字段
        AppState.mails = response.items || [];
        AppState.selectedMailId = null; // 清除选中的邮件ID

        // 更新邮件分页状态
        AppState.mailTotalCount = response.total || 0;
        AppState.mailTotalPages = Math.ceil(AppState.mailTotalCount / AppState.mailPageSize);
        updateMailPagination();

        renderMails();

        // 如果有邮件，自动选择第一封
        if (AppState.mails.length > 0) {
            selectMailByIndex(0);
        } else {
            // 没有邮件时清空显示区域
            elements.mailSubject.textContent = '暂无邮件';
            elements.mailFrom.textContent = '';
            elements.mailTo.textContent = '';
            elements.mailTime.textContent = '';
            elements.mailContent.innerHTML = '<div style="text-align: center; padding: 40px; color: var(--muted);">当前邮箱暂无邮件</div>';
        }
    } catch (error) {
        console.error('Failed to load mails:', error);
        console.error('Error details:', error.message, error.stack);
        elements.mailsListBody.innerHTML = `<tr><td colspan="7" style="text-align: center; padding: 20px; color: var(--muted);">加载邮件失败: ${error.message}</td></tr>`;
    }
}

function renderMails() {
    const tbody = elements.mailsListBody;

    if (AppState.mails.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 40px; color: var(--muted);">暂无邮件数据</td></tr>';
        return;
    }

    const mailsHtml = AppState.mails.map((mail, index) => {
        // 优先显示发件人名字，如果没有则显示邮箱地址
        const fromName = mail.from_name || '';
        const fromAddr = mail.from_addr || '';
        const displayName = fromName ? `${fromName} <${fromAddr}>` : fromAddr || '未知发件人';

        const subject = mail.subject || '无主题';
        const preview = mail.snippet || mail.bodyPreview || '';
        const time = formatTime(mail.received_at);
        const size = formatSize(mail.size_bytes || 0);
        const mailId = mail.id || `mail_${index}`;

        return `
            <tr class="mail-row ${mailId === AppState.selectedMailId ? 'selected' : ''}"
                data-mail-id="${mailId}" data-mail-index="${index}">
                <td>
                    <input type="checkbox" class="mail-checkbox mail-select">
                </td>
                <td>${index + 1}</td>
                <td>
                    <div class="mail-subject" title="${subject}">${subject}</div>
                </td>
                <td class="mail-meta">${displayName}</td>
                <td class="mail-meta">${preview.substring(0, 50)}...</td>
                <td class="mail-meta">${time}</td>
                <td class="mail-meta">${size}</td>
            </tr>
        `;
    }).join('');

    tbody.innerHTML = mailsHtml;

    // 添加事件监听
    tbody.querySelectorAll('.mail-row').forEach(row => {
        row.addEventListener('click', (e) => {
            // 如果点击的是checkbox，不选中邮件
            if (e.target.classList.contains('mail-checkbox')) {
                return;
            }

            const mailIndex = parseInt(row.dataset.mailIndex);
            selectMailByIndex(mailIndex);
        });

        // 右键菜单
        row.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            showMailContextMenu(e, row.dataset.mailId);
        });
    });

    // 全选checkbox
    elements.selectAllMails.addEventListener('change', (e) => {
        const checkboxes = tbody.querySelectorAll('.mail-select');
        checkboxes.forEach(cb => cb.checked = e.target.checked);
    });
}

async function selectMailByIndex(index) {
    AppState.selectedMailId = AppState.mails[index]?.id || `mail_${index}`;

    // 更新UI
    document.querySelectorAll('.mail-row').forEach(row => {
        row.classList.toggle('selected', parseInt(row.dataset.mailIndex) === index);
    });

    // 加载邮件详情
    const mail = AppState.mails[index];
    if (mail && mail.id) {
        try {
            // 显示加载中状态
            elements.mailSubject.textContent = '加载邮件内容中...';
            elements.mailFrom.textContent = '';
            elements.mailTo.textContent = '';
            elements.mailTime.textContent = '';
            elements.mailContent.innerHTML = '<div style="text-align: center; padding: 40px; color: var(--muted);">正在获取邮件内容...</div>';

            // 调用API获取邮件详情
            const response = await api.mails.detail(mail.id);

            if (response && response.body && (response.body.body_html || response.body.body_plain)) {
                // 如果有内容，直接显示
                renderMailDetail(response);
            } else {
                // 如果没有内容，显示下载按钮
                showMailDownloadOption(mail);
            }
        } catch (error) {
            console.error('Failed to load mail detail:', error);
            // 如果获取失败，显示下载按钮
            showMailDownloadOption(mail);
        }
    }
}

function selectMail(mailId) {
    AppState.selectedMailId = mailId;

    // 更新UI
    document.querySelectorAll('.mail-row').forEach(row => {
        row.classList.toggle('selected', parseInt(row.dataset.mailId) === mailId);
    });

    // 加载邮件详情
    loadMailDetail(mailId);
}

function renderMailDetail(mail) {
    elements.mailSubject.textContent = mail.subject || '无主题';

    // 处理发件人显示 - 优先显示名字，加上邮箱地址
    let fromDisplay = '未知发件人';
    if (mail.from_name) {
        fromDisplay = mail.from_addr ? `${mail.from_name} <${mail.from_addr}>` : mail.from_name;
    } else if (mail.from_addr) {
        fromDisplay = mail.from_addr;
    }
    elements.mailFrom.textContent = `发件人: ${fromDisplay}`;

    // 处理收件人
    let recipients = '未知';
    if (mail.to_joined) {
        recipients = mail.to_joined;
    } else if (Array.isArray(mail.to)) {
        recipients = mail.to.map(t => t.emailAddress?.name || t.emailAddress?.address || t).join(', ');
    } else if (typeof mail.to === 'string') {
        recipients = mail.to;
    }
    elements.mailTo.textContent = `收件人: ${recipients}`;

    elements.mailTime.textContent = `时间: ${formatTime(mail.received_at)}`;

    if (mail.body && (mail.body.body_html || mail.body.body_plain)) {
        // 创建完全隔离的内容容器
        const content = mail.body.body_html || `<pre style="white-space: pre-wrap; margin: 0; font-family: monospace;">${mail.body.body_plain}</pre>`;

        // 清空现有内容
        elements.mailContent.innerHTML = '';

        // 使用iframe完全隔离邮件内容
        const iframe = document.createElement('iframe');
        iframe.className = 'mail-content-iframe';
        iframe.style.cssText = `
            width: 100%;
            height: 100%;
            border: 1px solid #eee;
            border-radius: 4px;
        `;

        elements.mailContent.appendChild(iframe);

        // 等待iframe加载完成
        iframe.onload = function() {
            const doc = iframe.contentDocument || iframe.contentWindow.document;

            // 写入基础HTML结构
            doc.open();
            doc.write(`
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="utf-8">
                    <style>
                        body {
                            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                            font-size: 14px;
                            line-height: 1.6;
                            color: #333;
                            margin: 8px;
                            padding: 0;
                            background: white;
                        }
                        * {
                            box-sizing: border-box;
                            max-width: 100%;
                        }
                        img {
                            max-width: 100%;
                            height: auto;
                        }
                        table {
                            max-width: 100%;
                            overflow-x: auto;
                        }
                        a {
                            color: #1976d2;
                            text-decoration: underline;
                        }
                        a:hover {
                            text-decoration: none;
                        }
                        pre {
                            margin: 0;
                            white-space: pre-wrap;
                            font-family: 'Courier New', monospace;
                        }
                        /* 重置可能的样式污染 */
                        div, span, p, td, th, li {
                            background: transparent !important;
                        }
                    </style>
                </head>
                <body>
                    ${content}
                </body>
                </html>
            `);
            doc.close();
        };

        // 清除iframe内容以触发load事件
        iframe.src = 'about:blank';
    } else {
        elements.mailContent.innerHTML = `
            <div style="display: flex; align-items: center; justify-content: center; height: 100%; flex-direction: column; gap: 16px;">
                <p style="margin-bottom: 16px; color: var(--muted); font-size: 14px;">邮件内容未下载</p>
                <button id="downloadBtn2-${mail.id}"
                        onclick="downloadMail(${mail.id})"
                        style="padding: 12px 24px; background: #2196F3; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 500; transition: background-color 0.2s; font-family: inherit;">
                    下载邮件
                </button>
            </div>
        `;

        // 添加事件监听器
        setTimeout(() => {
            const downloadBtn = document.getElementById(`downloadBtn2-${mail.id}`);
            if (downloadBtn) {
                downloadBtn.addEventListener('mouseenter', () => {
                    downloadBtn.style.background = '#1976D2';
                    downloadBtn.style.color = 'white';
                });

                downloadBtn.addEventListener('mouseleave', () => {
                    downloadBtn.style.background = '#2196F3';
                    downloadBtn.style.color = 'white';
                });

                downloadBtn.addEventListener('mousedown', () => {
                    downloadBtn.style.background = '#1565C0';
                });

                downloadBtn.addEventListener('mouseup', () => {
                    downloadBtn.style.background = '#1976D2';
                });
            }
        }, 50);
    }
}

function showMailDownloadOption(mail) {
    elements.mailSubject.textContent = mail.subject || '无主题';

    // 处理发件人显示
    let fromDisplay = '未知发件人';
    if (mail.from_name) {
        fromDisplay = mail.from_addr ? `${mail.from_name} <${mail.from_addr}>` : mail.from_name;
    } else if (mail.from_addr) {
        fromDisplay = mail.from_addr;
    }
    elements.mailFrom.textContent = `发件人: ${fromDisplay}`;

    // 处理收件人
    let recipients = mail.to_joined || '未知收件人';
    elements.mailTo.textContent = `收件人: ${recipients}`;

    elements.mailTime.textContent = `时间: ${formatTime(mail.received_at)}`;

    // 显示下载按钮
    elements.mailContent.innerHTML = `
        <div style="display: flex; align-items: center; justify-content: center; height: 100%; flex-direction: column; gap: 16px;">
            <p style="margin-bottom: 16px; color: var(--muted); font-size: 14px;">该邮件内容尚未下载</p>
            <button id="downloadBtn-${mail.id}"
                    onclick="downloadMailContent(${mail.id})"
                    style="padding: 12px 24px; background: #2196F3; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; font-weight: 500; transition: background-color 0.2s; font-family: inherit;">
                下载邮件内容
            </button>
        </div>
    `;

    // 添加事件监听器处理悬停效果
    setTimeout(() => {
        const downloadBtn = document.getElementById(`downloadBtn-${mail.id}`);
        if (downloadBtn) {
            downloadBtn.addEventListener('mouseenter', () => {
                downloadBtn.style.background = '#1976D2';
                downloadBtn.style.color = 'white';
            });

            downloadBtn.addEventListener('mouseleave', () => {
                downloadBtn.style.background = '#2196F3';
                downloadBtn.style.color = 'white';
            });

            downloadBtn.addEventListener('mousedown', () => {
                downloadBtn.style.background = '#1565C0';
            });

            downloadBtn.addEventListener('mouseup', () => {
                downloadBtn.style.background = '#1976D2';
            });
        }
    }, 50);
}

async function downloadMailContent(mailId) {
    try {
        // 显示下载中状态
        elements.mailContent.innerHTML = '<div style="text-align: center; padding: 40px; color: var(--muted);">正在下载邮件内容...</div>';

        // 调用下载API
        const response = await api.mails.download(mailId);

        if (response.success) {
            showToast('邮件内容下载成功', 'success');
            // 重新获取邮件详情并显示
            const mailDetail = await api.mails.detail(mailId);
            renderMailDetail(mailDetail);
        } else {
            throw new Error(response.message || '下载失败');
        }
    } catch (error) {
        console.error('Download mail content failed:', error);
        showToast(`下载邮件内容失败: ${error.message}`, 'error');

        // 恢复显示下载按钮
        const mail = AppState.mails.find(m => m.id === mailId);
        if (mail) {
            showMailDownloadOption(mail);
        }
    }
}

// ==================== Context Menus ====================
function showAccountContextMenu(e, accountId) {
    const menu = elements.accountContextMenu;
    const account = AppState.accounts.find(a => a.id === accountId);

    if (!account) return;

    // 设置位置，防止溢出屏幕
    const x = Math.min(e.clientX, window.innerWidth - menu.offsetWidth);
    const y = Math.min(e.clientY, window.innerHeight - menu.offsetHeight);

    menu.style.left = `${x}px`;
    menu.style.top = `${y}px`;
    menu.style.display = 'block';

    // 移除之前的事件监听器
    menu.onclick = null;

    // 为所有菜单项（包括子菜单）添加点击事件
    const allMenuItems = menu.querySelectorAll('.context-menu-item');
    allMenuItems.forEach(item => {
        item.onclick = (event) => {
            event.stopPropagation();
            const action = event.target.closest('.context-menu-item').dataset.action;
            if (action) {
                console.log('Menu clicked:', action); // 调试信息
                handleAccountAction(action, accountId);
                menu.style.display = 'none';
            }
        };
    });

    // 添加全局点击事件来关闭菜单
    const closeMenu = (event) => {
        if (!menu.contains(event.target)) {
            menu.style.display = 'none';
            document.removeEventListener('click', closeMenu);
        }
    };

    // 延迟添加全局点击事件，避免立即触发
    setTimeout(() => {
        document.addEventListener('click', closeMenu);
    }, 100);
}

function showMailContextMenu(e, mailId) {
    const menu = elements.mailContextMenu;

    // 设置位置
    const x = Math.min(e.clientX, window.innerWidth - menu.offsetWidth);
    const y = Math.min(e.clientY, window.innerHeight - menu.offsetHeight);

    menu.style.left = `${x}px`;
    menu.style.top = `${y}px`;
    menu.style.display = 'block';

    // 添加点击事件
    menu.onclick = (event) => {
        const action = event.target.dataset.action;
        if (!action) return;

        handleMailAction(action, mailId);
        menu.style.display = 'none';
    };
}

function handleAccountAction(action, accountId) {
    const account = AppState.accounts.find(a => a.id === accountId);
    if (!account) return;

    switch (action) {
        case 'login':
            // 如果已经登录，显示提示信息
            if (account.status === '登录成功') {
                showToast(`账号 ${account.email} 已登录`, 'info');
                return;
            }
            loginAccount(accountId);
            break;
        case 'copy-email':
            copyAccountEmail(accountId);
            break;
        case 'helpers':
            manageHelperAccounts(accountId);
            break;
        case 'sync-all':
            syncAccount(accountId, 'full');
            break;
        case 'sync-recent':
            syncAccount(accountId, 'recent');
            break;
        case 'sync-today':
            syncAccount(accountId, 'today');
            break;
        case 'view-history':
            viewAccountHistory(accountId);
            break;
        case 'delete':
            deleteAccount(accountId);
            break;
    }
}

function handleMailAction(action, mailId) {
    switch (action) {
        case 'download-mail':
            downloadMail(mailId);
            break;
        case 'download-selected':
            downloadSelectedMails();
            break;
        case 'delete-mail':
            deleteMail(mailId);
            break;
        case 'delete-selected':
            deleteSelectedMails();
            break;
    }
}

// ==================== Utility Functions ====================
function formatTime(timeStr) {
    if (!timeStr) return '未知时间';

    const date = new Date(timeStr);
    const now = new Date();
    const diffMs = now - date;
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    console.log('formatTime debug:', {
        timeStr,
        date,
        now,
        diffMs,
        diffDays
    });

    if (diffDays === 0) {
        // 今天：显示月-日 时:分
        const month = (date.getMonth() + 1).toString().padStart(2, '0');
        const day = date.getDate().toString().padStart(2, '0');
        const hours = date.getHours().toString().padStart(2, '0');
        const minutes = date.getMinutes().toString().padStart(2, '0');
        return `${month}-${day} ${hours}:${minutes}`;
    } else if (diffDays === 1) {
        // 昨天：显示"昨天 时:分"
        const hours = date.getHours().toString().padStart(2, '0');
        const minutes = date.getMinutes().toString().padStart(2, '0');
        return `昨天 ${hours}:${minutes}`;
    } else if (diffDays < 7) {
        // 一周内：显示X天前
        return `${diffDays}天前`;
    } else if (diffDays <= 30) {
        // 一个月内：显示月-日 时:分
        const month = (date.getMonth() + 1).toString().padStart(2, '0');
        const day = date.getDate().toString().padStart(2, '0');
        const hours = date.getHours().toString().padStart(2, '0');
        const minutes = date.getMinutes().toString().padStart(2, '0');
        return `${month}-${day} ${hours}:${minutes}`;
    } else {
        // 更久：显示月-日
        const month = (date.getMonth() + 1).toString().padStart(2, '0');
        const day = date.getDate().toString().padStart(2, '0');
        return `${month}-${day}`;
    }
}

function formatSize(bytes) {
    if (!bytes) return '-';

    const units = ['B', 'KB', 'MB', 'GB'];
    let size = bytes;
    let unitIndex = 0;

    while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024;
        unitIndex++;
    }

    return `${size.toFixed(1)} ${units[unitIndex]}`;
}

function showToast(message, type = 'info') {
    // 简单的提示实现，可以后续改进
    console.log(`${type.toUpperCase()}: ${message}`);
    // 可以添加更美观的toast组件
}

async function copyAccountEmail(accountId) {
    const account = AppState.accounts.find(a => a.id === accountId);
    if (account) {
        try {
            await navigator.clipboard.writeText(account.email);
            showToast('邮箱已复制到剪贴板', 'success');
        } catch (error) {
            showToast('复制失败', 'error');
        }
    }
}

async function copyAccountPassword(accountId) {
    try {
        const account = await api.accounts.get(accountId);
        if (account.password) {
            await navigator.clipboard.writeText(account.password);
            showToast('密码已复制到剪贴板', 'success');
        }
    } catch (error) {
        showToast('获取密码失败', 'error');
    }
}

function showLoginDialog(accountId) {
    const account = AppState.accounts.find(a => a.id === accountId);
    if (!account) return;

    // 如果已经登录，显示信息
    if (account.status === '登录成功') {
        showToast('账号已登录', 'info');
        return;
    }

    // 使用OAuth登录
    loginAccount(accountId);
}

function viewAccountHistory(accountId) {
    // 查看历史版本 - 使用正确的API接口
    api.accounts.getHistory(accountId, { page: 1, size: 20 }).then(response => {
        if (response.items && response.items.length > 0) {
            // 显示历史版本对话框
            showHistoryDialog(accountId, response.items);
        } else {
            showToast('该账号没有历史版本', 'info');
        }
    }).catch(error => {
        console.error('获取历史版本失败:', error);
        showToast('获取历史版本失败', 'error');
    });
}

function showHistoryDialog(accountId, versions) {
    // 创建历史版本对话框
    const dialog = document.createElement('div');
    dialog.className = 'history-dialog';
    dialog.style.cssText = `
        position: fixed;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
        z-index: 1000;
        max-width: 900px;
        width: 90%;
        max-height: 85vh;
        overflow: hidden;
        display: flex;
        flex-direction: column;
    `;

    dialog.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 20px 20px 0 20px; border-bottom: 1px solid var(--border);">
            <h3 style="margin: 0; color: var(--text);">历史版本管理</h3>
            <button onclick="this.closest('.history-dialog').remove()"
                    style="background: none; border: none; font-size: 24px; cursor: pointer; color: var(--muted); padding: 0;">×</button>
        </div>

        <div style="display: flex; flex: 1; overflow: hidden;">
            <!-- 上部分：历史版本列表 -->
            <div style="width: 50%; border-right: 1px solid var(--border); display: flex; flex-direction: column;">
                <div style="padding: 12px 20px; background: var(--bg); border-bottom: 1px solid var(--border);">
                    <h4 style="margin: 0; font-size: 14px; color: var(--text);">版本列表</h4>
                </div>
                <div style="flex: 1; overflow-y: auto; padding: 8px 0;">
                    ${versions.length > 0 ? versions.map((v, index) => `
                        <div class="version-item" data-version="${v.version}"
                             style="padding: 12px 20px; cursor: pointer; border-bottom: 1px solid var(--hover-bg);
                                    transition: background-color 0.2s; ${index === 0 ? 'background: var(--hover-bg);' : ''}"
                             onclick="selectVersion(${v.version}, this)">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <div style="font-weight: 600; color: var(--text); margin-bottom: 4px;">版本 ${v.version}</div>
                                    <div style="font-size: 12px; color: var(--muted);">
                                        ${v.email || '未知邮箱'} | ${v.created_at || '未知时间'}
                                    </div>
                                </div>
                                <div style="text-align: right;">
                                    <div style="font-size: 12px; color: var(--muted); margin-bottom: 2px;">${v.name || '未知姓名'}</div>
                                    <div style="font-size: 11px; color: var(--muted);">${v.birthday || '未知生日'}</div>
                                </div>
                            </div>
                        </div>
                    `).join('') : `
                        <div style="padding: 40px 20px; text-align: center; color: var(--muted);">
                            暂无历史版本
                        </div>
                    `}
                </div>
            </div>

            <!-- 下部分：详细信息表单 -->
            <div style="width: 50%; display: flex; flex-direction: column;">
                <div style="padding: 12px 20px; background: var(--bg); border-bottom: 1px solid var(--border);">
                    <h4 style="margin: 0; font-size: 14px; color: var(--text);">详细信息</h4>
                </div>
                <div style="flex: 1; overflow-y: auto; padding: 20px;">
                    <form id="versionForm" style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
                        <div style="grid-column: 1;">
                            <label style="display: block; margin-bottom: 6px; font-size: 12px; font-weight: 500; color: var(--text);">邮箱:</label>
                            <input type="email" id="formEmail" readonly
                                   style="width: 100%; padding: 8px; border: 1px solid var(--border); border-radius: 4px;
                                          background: var(--bg); color: var(--muted); font-size: 13px;">
                        </div>
                        <div style="grid-column: 2;">
                            <label style="display: block; margin-bottom: 6px; font-size: 12px; font-weight: 500; color: var(--text);">密码:</label>
                            <input type="text" id="formPassword" readonly
                                   style="width: 100%; padding: 8px; border: 1px solid var(--border); border-radius: 4px;
                                          background: var(--bg); color: var(--muted); font-size: 13px;">
                        </div>
                        <div style="grid-column: 1;">
                            <label style="display: block; margin-bottom: 6px; font-size: 12px; font-weight: 500; color: var(--text);">姓名:</label>
                            <input type="text" id="formName" readonly
                                   style="width: 100%; padding: 8px; border: 1px solid var(--border); border-radius: 4px;
                                          background: var(--bg); color: var(--muted); font-size: 13px;">
                        </div>
                        <div style="grid-column: 2;">
                            <label style="display: block; margin-bottom: 6px; font-size: 12px; font-weight: 500; color: var(--text);">生日:</label>
                            <input type="text" id="formBirthday" readonly
                                   style="width: 100%; padding: 8px; border: 1px solid var(--border); border-radius: 4px;
                                          background: var(--bg); color: var(--muted); font-size: 13px;">
                        </div>
                        <div style="grid-column: 1 / -1;">
                            <label style="display: block; margin-bottom: 6px; font-size: 12px; font-weight: 500; color: var(--text);">辅助邮箱/电话:</label>
                            <div id="helperContacts" style="display: flex; flex-direction: column; gap: 8px;">
                                <!-- 动态生成辅助联系信息 -->
                            </div>
                        </div>
                        <div style="grid-column: 1 / -1;">
                            <label style="display: block; margin-bottom: 6px; font-size: 12px; font-weight: 500; color: var(--text);">别名:</label>
                            <div id="aliasesList" style="display: flex; flex-wrap: wrap; gap: 8px;">
                                <!-- 动态生成别名标签 -->
                            </div>
                        </div>
                        <div style="grid-column: 1 / -1;">
                            <label style="display: block; margin-bottom: 6px; font-size: 12px; font-weight: 500; color: var(--text);">备注:</label>
                            <textarea id="formNote" readonly rows="3"
                                      style="width: 100%; padding: 8px; border: 1px solid var(--border); border-radius: 4px;
                                             background: var(--bg); color: var(--muted); font-size: 13px; resize: vertical;"></textarea>
                        </div>
                        <div style="grid-column: 1 / -1;">
                            <label style="display: block; margin-bottom: 6px; font-size: 12px; font-weight: 500; color: var(--text);">操作者:</label>
                            <input type="text" id="formOperator" readonly
                                   style="width: 100%; padding: 8px; border: 1px solid var(--border); border-radius: 4px;
                                          background: var(--bg); color: var(--muted); font-size: 13px;">
                        </div>
                    </form>
                </div>
            </div>
        </div>

        <div style="padding: 16px 20px; border-top: 1px solid var(--border); display: flex; gap: 12px; justify-content: flex-end;">
            <button onclick="this.closest('.history-dialog').remove()"
                    style="padding: 8px 16px; background: var(--bg); color: var(--text); border: 1px solid var(--border);
                           border-radius: 4px; cursor: pointer; font-size: 13px;">取消</button>
            <button id="rollbackBtn" onclick="rollbackToVersion(${accountId})"
                    style="padding: 8px 16px; background: var(--warning); color: white; border: none;
                           border-radius: 4px; cursor: pointer; font-size: 13px;" disabled>回滚版本</button>
            <button id="saveVersionBtn" onclick="saveVersionChanges(${accountId})"
                    style="padding: 8px 16px; background: var(--primary); color: white; border: none;
                           border-radius: 4px; cursor: pointer; font-size: 13px;" disabled>保存修改</button>
        </div>
    `;

    // 添加全局函数
    window.selectVersion = function(version, element) {
        // 更新选中状态
        document.querySelectorAll('.version-item').forEach(item => {
            item.style.background = 'transparent';
        });
        element.style.background = 'var(--hover-bg)';

        // 获取版本数据
        const versionData = versions.find(v => v.version == version);
        if (versionData) {
            // 填充表单数据
            document.getElementById('formEmail').value = versionData.email || '';
            document.getElementById('formPassword').value = versionData.password || '';
            document.getElementById('formName').value = versionData.name || '';
            document.getElementById('formBirthday').value = versionData.birthday || '';
            document.getElementById('formNote').value = versionData.note || '';
            document.getElementById('formOperator').value = versionData.created_by || '';

            // 填充辅助联系信息
            const helperContacts = document.getElementById('helperContacts');
            const helpers = [];
            if (versionData.recovery_email) helpers.push(`邮箱: ${versionData.recovery_email}`);
            if (versionData.recovery_phone) helpers.push(`电话: ${versionData.recovery_phone}`);
            helperContacts.innerHTML = helpers.length > 0 ?
                helpers.map(helper => `
                    <div style="padding: 8px; background: var(--bg); border: 1px solid var(--border); border-radius: 4px; font-size: 12px; color: var(--text);">
                        ${helper}
                    </div>
                `).join('') :
                '<div style="color: var(--muted); font-size: 12px;">无辅助联系信息</div>';

            // 填充别名
            const aliasesList = document.getElementById('aliasesList');
            const aliases = versionData.aliases || [];
            aliasesList.innerHTML = aliases.length > 0 ?
                aliases.map(alias => `
                    <span style="padding: 4px 8px; background: var(--primary-light); color: var(--primary);
                               border-radius: 12px; font-size: 11px;">${alias}</span>
                `).join('') :
                '<div style="color: var(--muted); font-size: 12px;">无别名</div>';

            // 启用按钮
            document.getElementById('rollbackBtn').disabled = false;
            document.getElementById('saveVersionBtn').disabled = false;

            // 存储当前选中的版本
            window.selectedVersion = versionData;
        }
    };

    window.rollbackToVersion = function(accountId) {
        if (!window.selectedVersion) return;

        if (confirm(`确定要回滚到版本 ${window.selectedVersion.version} 吗？这将恢复该版本的所有数据。`)) {
            api.accounts.restore(accountId, {
                version: window.selectedVersion.version,
                note: `从版本 ${window.selectedVersion.version} 回滚`,
                created_by: '用户'
            }).then(response => {
                if (response.success) {
                    showToast('版本回滚成功', 'success');
                    loadAccounts();
                    dialog.remove();
                } else {
                    showToast(`回滚失败: ${response.message}`, 'error');
                }
            }).catch(error => {
                console.error('回滚版本失败:', error);
                showToast('回滚版本失败', 'error');
            });
        }
    };

    window.saveVersionChanges = function(accountId) {
        if (!window.selectedVersion) return;

        // 收集表单数据并更新版本信息
        const updatedData = {
            ...window.selectedVersion,
            note: document.getElementById('formNote').value,
            created_by: '用户'
        };

        // 这里可以调用API更新版本信息
        api.accounts.update(accountId, updatedData).then(response => {
            showToast('版本信息已更新', 'success');
            dialog.remove();
        }).catch(error => {
            console.error('保存版本失败:', error);
            showToast('保存版本失败', 'error');
        });
    };

    // 默认选择第一个版本
    if (versions.length > 0) {
        setTimeout(() => {
            const firstVersion = document.querySelector('.version-item');
            if (firstVersion) {
                selectVersion(versions[0].version, firstVersion);
            }
        }, 100);
    }

    document.body.appendChild(dialog);
}

function restoreVersion(accountId, version) {
    const note = prompt(`请输入恢复备注（恢复到版本 ${version}）`);
    if (!note) return;

    api.accounts.restore(accountId, {
        version: version,
        note: note,
        created_by: '用户'
    }).then(response => {
        if (response.success) {
            showToast('版本恢复成功', 'success');
            loadAccounts();
            document.body.removeChild(document.querySelector('div[style*="position: fixed"]'));
        } else {
            showToast(`恢复失败: ${response.message}`, 'error');
        }
    }).catch(error => {
        console.error('恢复版本失败:', error);
        showToast('恢复版本失败', 'error');
    });
}

async function deleteAccount(accountId) {
    if (confirm('确定要删除这个账号吗？此操作不可撤销。')) {
        try {
            await api.accounts.delete(accountId);
            showToast('账号已删除', 'success');
            loadAccounts(); // 重新加载列表
        } catch (error) {
            showToast('删除失败', 'error');
        }
    }
}

async function loginAccount(accountId) {
    const account = AppState.accounts.find(a => a.id === accountId);
    if (!account) return;

    
    // 如果没有密码，弹出输入框
    if (!account.password) {
        const password = prompt('请输入账号密码:');
        if (!password) return;

        // 临时更新账号数据
        account.password = password;
    }

    try {
        const response = await api.oauth.login({
            email: account.email,
            password: account.password,
            recovery_email: account.recovery_email || '',
            recovery_phone: account.recovery_phone || ''
        });

        if (response.success) {
            showToast('登录成功', 'success');

            // 更新账号状态
            account.status = '登录成功';

            // 重新渲染账号列表
            renderAccounts();
        } else {
            showToast(`登录失败: ${response.error}`, 'error');
        }
    } catch (error) {
        console.error('登录失败:', error);
        showToast('登录失败', 'error');
    }
}

function manageHelperAccounts(accountId) {
    const account = AppState.accounts.find(a => a.id === accountId);
    if (!account) return;

    // 创建辅助账号密码管理对话框
    const dialog = document.createElement('div');
    dialog.className = 'helper-dialog';
    dialog.style.cssText = `
        position: fixed;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 24px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
        z-index: 1000;
        max-width: 500px;
        width: 90%;
        max-height: 80vh;
        overflow-y: auto;
    `;

    // 获取当前账号的辅助信息
    const recoveryEmail = account.recovery_email || '';
    const recoveryPhone = account.recovery_phone || '';
    const aliases = account.aliases || [];

    dialog.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
            <h3 style="margin: 0; color: var(--text);">辅助账号密码管理</h3>
            <button onclick="this.closest('.helper-dialog').remove()"
                    style="background: none; border: none; font-size: 24px; cursor: pointer; color: var(--muted); padding: 0;">×</button>
        </div>

        <div style="margin-bottom: 20px;">
            <label style="display: block; margin-bottom: 8px; font-weight: 500; color: var(--text);">主账号邮箱:</label>
            <input type="email" value="${account.email}" readonly
                   style="width: 100%; padding: 10px; border: 1px solid var(--border); border-radius: 4px; background: var(--bg); color: var(--text);">
        </div>

        <div style="margin-bottom: 20px;">
            <label style="display: block; margin-bottom: 8px; font-weight: 500; color: var(--text);">辅助邮箱:</label>
            <input type="email" id="recoveryEmail" placeholder="用于找回密码的邮箱"
                   value="${recoveryEmail}"
                   style="width: 100%; padding: 10px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: var(--text);">
        </div>

        <div style="margin-bottom: 20px;">
            <label style="display: block; margin-bottom: 8px; font-weight: 500; color: var(--text);">辅助手机:</label>
            <input type="tel" id="recoveryPhone" placeholder="用于找回密码的手机号"
                   value="${recoveryPhone}"
                   style="width: 100%; padding: 10px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: var(--text);">
        </div>

        <div style="margin-bottom: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <label style="font-weight: 500; color: var(--text);">别名邮箱:</label>
                <button onclick="addAliasField()"
                        style="background: var(--primary); color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 12px;">+ 添加别名</button>
            </div>
            <div id="aliasesContainer">
                ${aliases.length > 0 ? aliases.map((alias, index) => `
                    <div style="display: flex; gap: 8px; margin-bottom: 8px;" data-index="${index}">
                        <input type="email" value="${alias}" placeholder="别名邮箱"
                               style="flex: 1; padding: 8px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: var(--text);">
                        <button onclick="removeAliasField(this)"
                                style="background: var(--danger); color: white; border: none; padding: 8px; border-radius: 4px; cursor: pointer;">删除</button>
                    </div>
                `).join('') : `
                    <div style="display: flex; gap: 8px; margin-bottom: 8px;">
                        <input type="email" placeholder="别名邮箱"
                               style="flex: 1; padding: 8px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: var(--text);">
                        <button onclick="removeAliasField(this)"
                                style="background: var(--danger); color: white; border: none; padding: 8px; border-radius: 4px; cursor: pointer;">删除</button>
                    </div>
                `}
            </div>
        </div>

        <div style="display: flex; gap: 12px; justify-content: flex-end;">
            <button onclick="this.closest('.helper-dialog').remove()"
                    style="padding: 10px 20px; background: var(--bg); color: var(--text); border: 1px solid var(--border); border-radius: 4px; cursor: pointer;">取消</button>
            <button onclick="saveHelperAccounts(${accountId}, this)"
                    style="padding: 10px 20px; background: var(--primary); color: white; border: none; border-radius: 4px; cursor: pointer;">保存</button>
        </div>
    `;

    // 添加全局函数
    window.addAliasField = function() {
        const container = document.getElementById('aliasesContainer');
        const newIndex = container.children.length;
        const aliasField = document.createElement('div');
        aliasField.style.cssText = 'display: flex; gap: 8px; margin-bottom: 8px;';
        aliasField.innerHTML = `
            <input type="email" placeholder="别名邮箱"
                   style="flex: 1; padding: 8px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); color: var(--text);">
            <button onclick="removeAliasField(this)"
                    style="background: var(--danger); color: white; border: none; padding: 8px; border-radius: 4px; cursor: pointer;">删除</button>
        `;
        container.appendChild(aliasField);
    };

    window.removeAliasField = function(button) {
        button.parentElement.remove();
    };

    window.saveHelperAccounts = function(accountId, button) {
        const recoveryEmail = document.getElementById('recoveryEmail').value.trim();
        const recoveryPhone = document.getElementById('recoveryPhone').value.trim();
        const aliasInputs = document.querySelectorAll('#aliasesContainer input[type="email"]');
        const aliases = Array.from(aliasInputs)
            .map(input => input.value.trim())
            .filter(email => email !== '');

        // 更新账号数据
        const account = AppState.accounts.find(a => a.id === accountId);
        if (account) {
            account.recovery_email = recoveryEmail;
            account.recovery_phone = recoveryPhone;
            account.aliases = aliases;
        }

        // 调用API保存
        api.accounts.update(accountId, {
            recovery_email: recoveryEmail,
            recovery_phone: recoveryPhone,
            aliases: aliases
        }).then(response => {
            showToast('辅助账号密码信息已保存', 'success');
            dialog.remove();
        }).catch(error => {
            console.error('保存失败:', error);
            showToast('保存失败', 'error');
        });
    };

    document.body.appendChild(dialog);
}

async function downloadMail(mailId) {
    try {
        const response = await api.mails.get(mailId);

        // 创建下载链接
        const mailContent = JSON.stringify(response, null, 2);
        const blob = new Blob([mailContent], { type: 'application/json' });
        const url = URL.createObjectURL(blob);

        const a = document.createElement('a');
        a.href = url;
        a.download = `mail_${mailId}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        showToast('邮件下载成功', 'success');
    } catch (error) {
        console.error('下载邮件失败:', error);
        showToast('下载邮件失败', 'error');
    }
}

function downloadSelectedMails() {
    const selectedMails = Array.from(document.querySelectorAll('.mail-select:checked')).length;
    if (selectedMails === 0) {
        showToast('请先选择邮件', 'error');
        return;
    }

    showToast(`开始下载 ${selectedMails} 封邮件`, 'info');

    // 逐个下载选中的邮件
    document.querySelectorAll('.mail-select:checked').forEach((checkbox, index) => {
        const row = checkbox.closest('.mail-row');
        if (row) {
            const mailId = row.dataset.mailId;
            setTimeout(() => {
                downloadMail(mailId);
            }, index * 500); // 间隔500ms下载，避免同时下载过多
        }
    });
}

async function deleteMail(mailId) {
    if (confirm('确定要删除这封邮件吗？')) {
        try {
            await api.mails.delete(mailId);
            showToast('邮件已删除', 'success');
            loadAccountMails(AppState.selectedAccountId); // 重新加载列表
        } catch (error) {
            showToast('删除失败', 'error');
        }
    }
}

function deleteSelectedMails() {
    showToast('批量删除功能开发中...', 'info');
}

// ==================== Event Listeners ====================
function initEventListeners() {
    // 主题切换
    elements.themeSelector.addEventListener('change', (e) => {
        setTheme(e.target.value);
    });

    // Header搜索
    let searchTimeout;
    elements.searchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            const field = elements.searchField.value;
            const value = e.target.value.trim();
            const params = {};

            if (value) {
                params[`${field}_contains`] = value;
            }

            AppState.currentPage = 1;
            loadAccounts(params);
        }, 300);
    });

    // 分页
    elements.prevPageBtn.addEventListener('click', () => {
        if (AppState.accountCurrentPage > 1) {
            AppState.accountCurrentPage--;
            loadAccounts();
        }
    });

    elements.nextPageBtn.addEventListener('click', () => {
        if (AppState.accountCurrentPage < AppState.accountTotalPages) {
            AppState.accountCurrentPage++;
            loadAccounts();
        }
    });

    // 每页数量
    elements.pageSizeSelect.addEventListener('change', (e) => {
        AppState.accountPageSize = parseInt(e.target.value);
        AppState.accountCurrentPage = 1;
        AppState.selectedAccountIds.clear();
        loadAccounts();
    });

    // 批量操作按钮
    elements.bulkDeleteBtn.addEventListener('click', () => {
        elements.bulkDeleteBtn.classList.add('danger');
        bulkDeleteAccounts();
        elements.bulkDeleteBtn.classList.remove('danger');
    });

    elements.bulkNoteBtn.addEventListener('click', bulkUpdateNote);

    elements.bulkLoginBtn.addEventListener('click', bulkLogin);

    elements.bulkSyncBtn.addEventListener('click', bulkSync);

    // 新增账号
    elements.addAccountBtn.addEventListener('click', () => {
        showAddAccountDialog();
    });

    // 设置
    elements.settingsBtn.addEventListener('click', () => {
        showSettingsDialog();
    });

    // 邮件Tab切换
    elements.mailsTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            elements.mailsTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            AppState.mailTab = tab.dataset.tab;

            if (AppState.mailTab === 'search') {
                showToast('邮件全搜功能开发中...', 'info');
            }
        });
    });

    // 邮件搜索
    let mailSearchTimeout;
    elements.mailSearch.addEventListener('input', (e) => {
        clearTimeout(mailSearchTimeout);
        mailSearchTimeout = setTimeout(() => {
            const field = elements.mailSearchField.value;
            const value = e.target.value.trim();
            if (AppState.selectedAccountId) {
                const params = value ? {[field]: value} : {};
                loadAccountMails(AppState.selectedAccountId, params);
            }
        }, 300);
    });

    // 写邮件
    elements.composeBtn.addEventListener('click', () => {
        showComposeMailDialog();
    });

    // 邮件分页
    elements.mailPrevPageBtn.addEventListener('click', () => {
        if (AppState.mailCurrentPage > 1 && AppState.selectedAccountId) {
            AppState.mailCurrentPage--;
            loadAccountMails(AppState.selectedAccountId);
        }
    });

    elements.mailNextPageBtn.addEventListener('click', () => {
        if (AppState.mailCurrentPage < AppState.mailTotalPages && AppState.selectedAccountId) {
            AppState.mailCurrentPage++;
            loadAccountMails(AppState.selectedAccountId);
        }
    });

    // 邮件每页数量
    elements.mailPageSizeSelect.addEventListener('change', (e) => {
        if (AppState.selectedAccountId) {
            AppState.mailPageSize = parseInt(e.target.value);
            AppState.mailCurrentPage = 1;
            loadAccountMails(AppState.selectedAccountId);
        }
    });

    // 隐藏右键菜单
    document.addEventListener('click', () => {
        elements.accountContextMenu.style.display = 'none';
        elements.mailContextMenu.style.display = 'none';
    });
}


function initHeaderUser() {
    // 1. 显示用户信息
    const username = localStorage.getItem('username') || '用户';
    const role = localStorage.getItem('role') || '';

    const infoSpan = document.getElementById('headerUserInfo');
    if (infoSpan) {
        // 如果是管理员，显示角色；如果是普通用户，只显示名字
        const roleDisplay = role === 'admin' ? ' (管理员)' : '';
        infoSpan.textContent = `${username}${roleDisplay}`;
    }

    // 2. 绑定登出事件
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', handleLogout);
    }
}

function handleLogout() {
    if (confirm('确定要退出登录吗？')) {
        // 清除所有 LocalStorage
        localStorage.clear();
        // 跳转回登录页
        window.location.href = '/login.html';
    }
}
// ==================== Application Initialization ====================
function init() {
    // 首先检查API对象是否正确定义
    console.log('API object:', api);
    console.log('API.mails:', api.mails);

    if (!api || !api.mails) {
        console.error('API not properly initialized');
        alert('API初始化失败，请检查代码');
        return;
    }

    initTheme();
    initResizer();
    initEventListeners();
    initHeaderUser();
    loadSettings();
    loadAccounts();
}

function showAddAccountDialog() {
    const dialog = document.createElement('div');
    dialog.style.cssText = `
        position: fixed;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 20px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
        z-index: 1000;
        width: 400px;
    `;

    dialog.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
            <h3 style="margin: 0;">新增账号</h3>
            <button onclick="this.parentElement.parentElement.remove()" style="background: none; border: none; font-size: 20px; cursor: pointer;">×</button>
        </div>
        <div style="display: flex; flex-direction: column; gap: 10px;">
            <input type="text" id="newAccountEmail" placeholder="邮箱地址" style="padding: 8px; border: 1px solid var(--border); border-radius: 4px;">
            <input type="password" id="newAccountPassword" placeholder="密码" style="padding: 8px; border: 1px solid var(--border); border-radius: 4px;">
            <input type="text" id="newAccountRecoveryEmail" placeholder="辅助邮箱（可选）" style="padding: 8px; border: 1px solid var(--border); border-radius: 4px;">
            <input type="text" id="newAccountRecoveryPhone" placeholder="辅助电话（可选）" style="padding: 8px; border: 1px solid var(--border); border-radius: 4px;">
            <input type="text" id="newAccountNote" placeholder="备注" style="padding: 8px; border: 1px solid var(--border); border-radius: 4px;">
            <button onclick="addNewAccount()" style="padding: 10px; background: var(--primary); color: white; border: none; border-radius: 4px; cursor: pointer;">添加</button>
        </div>
    `;

    document.body.appendChild(dialog);
}

function addNewAccount() {
    const email = document.getElementById('newAccountEmail').value.trim();
    const password = document.getElementById('newAccountPassword').value.trim();
    const recoveryEmail = document.getElementById('newAccountRecoveryEmail').value.trim();
    const recoveryPhone = document.getElementById('newAccountRecoveryPhone').value.trim();
    const note = document.getElementById('newAccountNote').value.trim();

    if (!email || !password) {
        showToast('请输入邮箱和密码', 'error');
        return;
    }

    const accountData = {
        email: email,
        password: password,
        recovery_email: recoveryEmail,
        recovery_phone: recoveryPhone,
        note: note,
        status: '未登录'
    };

    api.accounts.create(accountData).then(response => {
        if (response.success || response.created) {
            showToast('账号添加成功', 'success');
            document.body.removeChild(document.querySelector('div[style*="position: fixed"]'));
            loadAccounts();
        } else {
            showToast(`添加失败: ${response.message}`, 'error');
        }
    }).catch(error => {
        console.error('添加账号失败:', error);
        showToast('添加账号失败', 'error');
    });
}

function showComposeMailDialog() {
    if (!AppState.selectedAccountId) {
        showToast('请先选择账号', 'error');
        return;
    }

    const dialog = document.createElement('div');
    dialog.style.cssText = `
        position: fixed;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 20px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
        z-index: 1000;
        width: 500px;
        max-height: 600px;
        overflow-y: auto;
    `;

    dialog.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
            <h3 style="margin: 0;">写邮件</h3>
            <button onclick="this.parentElement.parentElement.remove()" style="background: none; border: none; font-size: 20px; cursor: pointer;">×</button>
        </div>
        <div style="display: flex; flex-direction: column; gap: 10px;">
            <input type="text" id="mailTo" placeholder="收件人" style="padding: 8px; border: 1px solid var(--border); border-radius: 4px;">
            <input type="text" id="mailSubject" placeholder="主题" style="padding: 8px; border: 1px solid var(--border); border-radius: 4px;">
            <textarea id="mailBody" placeholder="邮件内容" style="padding: 8px; border: 1px solid var(--border); border-radius: 4px; min-height: 200px; resize: vertical;"></textarea>
            <button onclick="sendMail()" style="padding: 10px; background: var(--primary); color: white; border: none; border-radius: 4px; cursor: pointer;">发送</button>
        </div>
    `;

    document.body.appendChild(dialog);
}

function sendMail() {
    const to = document.getElementById('mailTo').value.trim();
    const subject = document.getElementById('mailSubject').value.trim();
    const body = document.getElementById('mailBody').value.trim();

    if (!to || !subject || !body) {
        showToast('请填写完整的邮件信息', 'error');
        return;
    }

    const mailData = {
        account_id: AppState.selectedAccountId,
        to: to.split(',').map(e => ({ emailAddress: { address: e.trim() } })),
        subject: subject,
        body: {
            contentType: 'text',
            content: body
        }
    };

    api.mails.create(mailData).then(response => {
        if (response.success || response.id) {
            showToast('邮件发送成功', 'success');
            document.body.removeChild(document.querySelector('div[style*="position: fixed"]'));
        } else {
            showToast(`发送失败: ${response.message}`, 'error');
        }
    }).catch(error => {
        console.error('发送邮件失败:', error);
        showToast('发送邮件失败', 'error');
    });
}

function showSettingsDialog() {
    const dialog = document.createElement('div');
    dialog.style.cssText = `
        position: fixed;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 20px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
        z-index: 1000;
        width: 400px;
    `;

    dialog.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
            <h3 style="margin: 0;">设置</h3>
            <button onclick="this.parentElement.parentElement.remove()" style="background: none; border: none; font-size: 20px; cursor: pointer;">×</button>
        </div>
        <div style="display: flex; flex-direction: column; gap: 15px;">
            <div>
                <label style="display: block; margin-bottom: 5px; font-weight: 600;">默认每页显示数量</label>
                <select id="defaultPageSize" style="width: 100%; padding: 8px; border: 1px solid var(--border); border-radius: 4px;">
                    <option value="20">20</option>
                    <option value="50" selected>50</option>
                    <option value="100">100</option>
                    <option value="200">200</option>
                </select>
            </div>
            <div>
                <label style="display: block; margin-bottom: 5px; font-weight: 600;">自动同步间隔（分钟）</label>
                <input type="number" id="syncInterval" placeholder="30" min="5" value="30" style="width: 100%; padding: 8px; border: 1px solid var(--border); border-radius: 4px;">
            </div>
            <div>
                <label style="display: flex; align-items: center; gap: 10px;">
                    <input type="checkbox" id="enableNotifications">
                    <span>启用通知提醒</span>
                </label>
            </div>
            <button onclick="saveSettings()" style="padding: 10px; background: var(--primary); color: white; border: none; border-radius: 4px; cursor: pointer;">保存设置</button>
        </div>
    `;

    document.body.appendChild(dialog);
}

function saveSettings() {
    const settings = {
        defaultPageSize: parseInt(document.getElementById('defaultPageSize').value),
        syncInterval: parseInt(document.getElementById('syncInterval').value),
        enableNotifications: document.getElementById('enableNotifications').checked
    };

    localStorage.setItem('appSettings', JSON.stringify(settings));
    showToast('设置已保存', 'success');
    document.body.removeChild(document.querySelector('div[style*="position: fixed"]'));

    // 应用设置
    AppState.pageSize = settings.defaultPageSize;
}

function loadSettings() {
    const savedSettings = localStorage.getItem('appSettings');
    if (savedSettings) {
        const settings = JSON.parse(savedSettings);
        AppState.pageSize = settings.defaultPageSize || 50;
        elements.pageSizeSelect.value = AppState.pageSize;
    }
}

// 启动应用
document.addEventListener('DOMContentLoaded', init);