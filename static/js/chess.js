// 全局变量
let socket;
let gameState = {
    isPlaying: false,
    isPaused: false,
    currentPlayer: 'red',
    moveCount: 0,
    startTime: null,
    boardState: null
};

// 更新当前执棋方显示
function updateCurrentPlayer(player) {
    const currentPlayerText = document.getElementById('current-player-text');
    if (currentPlayerText) {
        if (player === 'red') {
            currentPlayerText.textContent = '当前轮到红方执棋';
            currentPlayerText.className = 'red-turn';
        } else {
            currentPlayerText.textContent = '当前轮到黑方执棋';
            currentPlayerText.className = 'black-turn';
        }
    }
}

// 添加思考过程到指定的思考框
function addThinkingProcess(player, message) {
    const isRed = player === 'red' || player.includes('红方') || player.includes('OpenAI') || player.includes('GPT');
    const thinkingBoxId = isRed ? 'red-thinking-process' : 'black-thinking-process';
    const thinkingBox = document.getElementById(thinkingBoxId);
    
    if (thinkingBox) {
        // 创建思考项
        const thinkingItem = document.createElement('div');
        thinkingItem.className = `thinking-item ${isRed ? 'red-thinking' : 'black-thinking'}`;
        
        // 添加时间戳
        const timestamp = document.createElement('div');
        timestamp.className = 'thinking-timestamp';
        timestamp.textContent = new Date().toLocaleTimeString();
        
        // 添加思考内容
        const thinkingText = document.createElement('div');
        thinkingText.className = 'thinking-text';
        thinkingText.textContent = message;
        
        thinkingItem.appendChild(timestamp);
        thinkingItem.appendChild(thinkingText);
        
        // 如果是第一条消息，清空默认文本
        if (thinkingBox.innerHTML.includes('等待') || thinkingBox.innerHTML.includes('开始思考')) {
            thinkingBox.innerHTML = '';
        }
        
        thinkingBox.appendChild(thinkingItem);
        
        // 自动滚动到底部
        thinkingBox.scrollTop = thinkingBox.scrollHeight;
    }
}

// 清空思考过程
function clearThinkingProcess(player) {
    const isRed = player === 'red' || player.includes('红方') || player.includes('OpenAI') || player.includes('GPT');
    const thinkingBoxId = isRed ? 'red-thinking-process' : 'black-thinking-process';
    const thinkingBox = document.getElementById(thinkingBoxId);
    
    if (thinkingBox) {
        thinkingBox.innerHTML = `<p>等待${isRed ? '红方' : '黑方'}开始思考...</p>`;
    }
}

// 流式输出思考过程（模拟打字机效果）
function streamThinkingProcess(player, message, speed = 50) {
    const isRed = player === 'red' || player.includes('红方') || player.includes('OpenAI') || player.includes('GPT');
    const thinkingBoxId = isRed ? 'red-thinking-process' : 'black-thinking-process';
    const thinkingBox = document.getElementById(thinkingBoxId);
    
    if (thinkingBox) {
        // 创建思考项
        const thinkingItem = document.createElement('div');
        thinkingItem.className = `thinking-item ${isRed ? 'red-thinking' : 'black-thinking'}`;
        
        // 添加时间戳
        const timestamp = document.createElement('div');
        timestamp.className = 'thinking-timestamp';
        timestamp.textContent = new Date().toLocaleTimeString();
        
        // 添加思考内容容器
        const thinkingText = document.createElement('div');
        thinkingText.className = 'thinking-text';
        
        thinkingItem.appendChild(timestamp);
        thinkingItem.appendChild(thinkingText);
        
        // 如果是第一条消息，清空默认文本
        if (thinkingBox.innerHTML.includes('等待') || thinkingBox.innerHTML.includes('开始思考')) {
            thinkingBox.innerHTML = '';
        }
        
        thinkingBox.appendChild(thinkingItem);
        
        // 流式输出文字
        let index = 0;
        const typeWriter = () => {
            if (index < message.length) {
                thinkingText.textContent += message.charAt(index);
                index++;
                thinkingBox.scrollTop = thinkingBox.scrollHeight;
                setTimeout(typeWriter, speed);
            }
        };
        
        typeWriter();
    }
}

// 实时流式输出思考过程（用于Socket.IO流式数据）
let currentStreamingElements = {};

function streamThinkingProcessRealtime(player, content) {
    const thinkingBoxId = `${player}-thinking-process`;
    const thinkingBox = document.getElementById(thinkingBoxId);
    
    
    if (!thinkingBox) {
        console.error(`找不到思考区元素: ${thinkingBoxId}`);
        return;
    }
    
    // 如果是第一次为该玩家创建流式元素
    if (!currentStreamingElements[player]) {
        
        // 如果是第一条消息，清空默认文本
        if (thinkingBox.innerHTML.includes('等待') || thinkingBox.innerHTML.includes('开始思考')) {
            thinkingBox.innerHTML = '';
        }
        
        // 创建思考项
        const thinkingItem = document.createElement('div');
        thinkingItem.className = `thinking-item ${player === 'red' ? 'red-thinking' : 'black-thinking'}`;
        
        // 添加时间戳
        const timestamp = document.createElement('div');
        timestamp.className = 'thinking-timestamp';
        timestamp.textContent = new Date().toLocaleTimeString();
        
        // 添加思考内容容器
        const thinkingText = document.createElement('div');
        thinkingText.className = 'thinking-text';
        thinkingText.id = `${player}-current-stream`;
        
        thinkingItem.appendChild(timestamp);
        thinkingItem.appendChild(thinkingText);
        thinkingBox.appendChild(thinkingItem);
        
        // 保存当前流式元素的引用
        currentStreamingElements[player] = thinkingText;
    }
    
    // 追加内容到当前流式元素
    const streamElement = currentStreamingElements[player];
    if (streamElement) {
        streamElement.textContent += content;
        thinkingBox.scrollTop = thinkingBox.scrollHeight;
    } else {
        console.error(`${player}的流式元素不存在`);
    }
}

// 清理流式输出状态
function clearStreamingState(player) {
    if (currentStreamingElements[player]) {
        delete currentStreamingElements[player];
    }
}

// 中国象棋棋盘渲染器
class ChessBoardRenderer {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');
        
        // 增大的中国象棋棋盘尺寸比例 (9:10)
        this.boardWidth = 520;   // 9列
        this.boardHeight = 580;  // 10行
        this.margin = 40;
        
        this.canvas.width = this.boardWidth + this.margin * 2;
        this.canvas.height = this.boardHeight + this.margin * 2;
        
        this.cellWidth = this.boardWidth / 8;   // 8个间隔，9条线
        this.cellHeight = this.boardHeight / 9; // 9个间隔，10条线
        
        this.pieces = {};
        this.lastMove = null;
        
        this.initializePieces();
        this.drawBoard();
        this.showInitialPosition();
    }
    
    initializePieces() {
        // 中国象棋棋子字符
        this.pieces = {
            'K': '帅', 'A': '仕', 'B': '相', 'N': '馬', 'R': '车', 'C': '炮', 'P': '兵',
            'k': '将', 'a': '士', 'b': '象', 'n': '馬', 'r': '車', 'c': '炮', 'p': '卒'
        };
    }
    
    drawBoard() {
        // 清空画布
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        
        // 绘制传统木质背景
        this.ctx.fillStyle = '#F5DEB3';
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
        
        // 绘制棋盘边框
        this.ctx.strokeStyle = '#8B4513';
        this.ctx.lineWidth = 3;
        this.ctx.strokeRect(this.margin - 2, this.margin - 2, this.boardWidth + 4, this.boardHeight + 4);
        
        // 设置线条样式
        this.ctx.strokeStyle = '#000000';
        this.ctx.lineWidth = 1.5;
        
        // 绘制横线（10条）
        for (let i = 0; i <= 9; i++) {
            this.ctx.beginPath();
            this.ctx.moveTo(this.margin, this.margin + i * this.cellHeight);
            this.ctx.lineTo(this.margin + this.boardWidth, this.margin + i * this.cellHeight);
            this.ctx.stroke();
        }
        
        // 绘制竖线（9条）- 楚河汉界中间不连接
        for (let i = 0; i <= 8; i++) {
            // 上半部分竖线（黑方区域）
            this.ctx.beginPath();
            this.ctx.moveTo(this.margin + i * this.cellWidth, this.margin);
            this.ctx.lineTo(this.margin + i * this.cellWidth, this.margin + 4 * this.cellHeight);
            this.ctx.stroke();
            
            // 下半部分竖线（红方区域）
            this.ctx.beginPath();
            this.ctx.moveTo(this.margin + i * this.cellWidth, this.margin + 5 * this.cellHeight);
            this.ctx.lineTo(this.margin + i * this.cellWidth, this.margin + this.boardHeight);
            this.ctx.stroke();
        }
        
        // 绘制九宫格斜线
        this.drawPalaceDiagonals();
        
        // 绘制楚河汉界
        this.drawRiverBoundary();
        
        // 绘制兵卒位置标记
        this.drawPositionMarkers();
    }
    
    drawPalaceDiagonals() {
        this.ctx.strokeStyle = '#000000';
        this.ctx.lineWidth = 1.5;
        
        // 黑方九宫格斜线（顶部）
        this.ctx.beginPath();
        this.ctx.moveTo(this.margin + 3 * this.cellWidth, this.margin);
        this.ctx.lineTo(this.margin + 5 * this.cellWidth, this.margin + 2 * this.cellHeight);
        this.ctx.stroke();
        
        this.ctx.beginPath();
        this.ctx.moveTo(this.margin + 5 * this.cellWidth, this.margin);
        this.ctx.lineTo(this.margin + 3 * this.cellWidth, this.margin + 2 * this.cellHeight);
        this.ctx.stroke();
        
        // 红方九宫格斜线（底部）
        this.ctx.beginPath();
        this.ctx.moveTo(this.margin + 3 * this.cellWidth, this.margin + 7 * this.cellHeight);
        this.ctx.lineTo(this.margin + 5 * this.cellWidth, this.margin + 9 * this.cellHeight);
        this.ctx.stroke();
        
        this.ctx.beginPath();
        this.ctx.moveTo(this.margin + 5 * this.cellWidth, this.margin + 7 * this.cellHeight);
        this.ctx.lineTo(this.margin + 3 * this.cellWidth, this.margin + 9 * this.cellHeight);
        this.ctx.stroke();
    }
    
    drawRiverBoundary() {
        // 绘制楚河汉界文字
        this.ctx.fillStyle = '#8B4513';
        this.ctx.font = 'bold 18px SimHei, Microsoft YaHei, Arial';
        this.ctx.textAlign = 'center';
        this.ctx.textBaseline = 'middle';
        
        const riverY = this.margin + 4.5 * this.cellHeight;
        
        this.ctx.fillText('楚河', this.margin + 2 * this.cellWidth, riverY);
        this.ctx.fillText('汉界', this.margin + 6 * this.cellWidth, riverY);
    }
    
    drawPositionMarkers() {
        this.ctx.strokeStyle = '#000000';
        this.ctx.lineWidth = 1;
        
        // 兵卒位置标记
        const positions = [
            // 黑方兵卒位置 (第3行)
            [0, 3], [2, 3], [4, 3], [6, 3], [8, 3],
            // 红方兵卒位置 (第6行)
            [0, 6], [2, 6], [4, 6], [6, 6], [8, 6],
            // 炮的位置 (第2行和第7行)
            [1, 2], [7, 2], [1, 7], [7, 7]
        ];
        
        positions.forEach(([col, row]) => {
            const x = this.margin + col * this.cellWidth;
            const y = this.margin + row * this.cellHeight;
            const size = 4;
            
            // 绘制十字标记
            this.ctx.beginPath();
            this.ctx.moveTo(x - size, y);
            this.ctx.lineTo(x + size, y);
            this.ctx.moveTo(x, y - size);
            this.ctx.lineTo(x, y + size);
            this.ctx.stroke();
        });
    }
    
    drawCoordinates() {
        this.ctx.fillStyle = '#8B4513';
        this.ctx.font = '12px Arial';
        this.ctx.textAlign = 'center';
        this.ctx.textBaseline = 'middle';
        
        // 列标识 (a-i) - 底部
        for (let i = 0; i < 9; i++) {
            const letter = String.fromCharCode(97 + i);
            this.ctx.fillText(letter, this.margin + i * this.cellWidth, this.canvas.height - 10);
        }
        
        // 行标识 (0-9) - 左侧
        for (let i = 0; i <= 9; i++) {
            this.ctx.fillText(i.toString(), 15, this.margin + i * this.cellHeight);
        }
    }
    
    showInitialPosition() {
        // 显示初始棋子位置
        const initialBoard = "rnbakabnr/........./.c.....c./p.p.p.p.p/........./........./P.P.P.P.P/.C.....C./........./RNBAKABNR";
        this.updateBoard(initialBoard);
    }
    
    updateBoard(boardState) {
        
        if (!boardState) {
            console.error('棋盘状态为空');
            return;
        }
        
        // 清空棋盘并重绘
        this.drawBoard();
        
        // 解析棋盘状态
        const rows = boardState.split('/');
        
        for (let row = 0; row < 10; row++) {
            if (rows[row]) {
                for (let col = 0; col < 9; col++) {
                    const piece = rows[row][col];
                    if (piece && piece !== '.') {
                        this.drawPiece(col, row, piece);
                    }
                }
            }
        }
        
        this.drawCoordinates();
        // 高亮最后一步
        if (this.lastMove) {
            this.highlightMove(this.lastMove);
        }
        
    }
    
    drawPiece(col, row, piece) {
        const x = this.margin + col * this.cellWidth;
        const y = this.margin + row * this.cellHeight;
        const radius = Math.min(this.cellWidth, this.cellHeight) * 0.4;
        
        // 绘制棋子阴影
        this.ctx.beginPath();
        this.ctx.arc(x + 2, y + 2, radius, 0, 2 * Math.PI);
        this.ctx.fillStyle = 'rgba(0, 0, 0, 0.2)';
        this.ctx.fill();
        
        // 绘制棋子背景
        this.ctx.beginPath();
        this.ctx.arc(x, y, radius, 0, 2 * Math.PI);
        
        if (piece === piece.toUpperCase()) {
            // 红方棋子 - 浅色背景
            this.ctx.fillStyle = '#FFF8DC';
        } else {
            // 黑方棋子 - 深色背景
            this.ctx.fillStyle = '#2F2F2F';
        }
        this.ctx.fill();
        
        // 绘制棋子边框
        this.ctx.strokeStyle = '#000000';
        this.ctx.lineWidth = 2;
        this.ctx.stroke();
        
        // 绘制棋子文字
        const pieceText = this.pieces[piece] || piece;
        this.ctx.font = `bold ${Math.min(this.cellWidth, this.cellHeight) * 0.5}px SimHei, Microsoft YaHei, Arial`;
        this.ctx.textAlign = 'center';
        this.ctx.textBaseline = 'middle';
        
        // 设置文字颜色
        if (piece === piece.toUpperCase()) {
            this.ctx.fillStyle = '#DC143C';  // 红方文字
        } else {
            this.ctx.fillStyle = '#FFFFFF';  // 黑方文字
        }
        
        this.ctx.fillText(pieceText, x, y);
    }
    
    highlightMove(move) {
        if (!move || !move.from || !move.to) return;
        
        const fromCol = move.from.charCodeAt(0) - 97;
        const fromRow = parseInt(move.from[1]);
        const toCol = move.to.charCodeAt(0) - 97;
        const toRow = parseInt(move.to[1]);
        
        // 高亮起始位置
        this.highlightSquare(fromCol, fromRow, '#FFD700', 0.4);
        // 高亮目标位置
        this.highlightSquare(toCol, toRow, '#FF6B6B', 0.4);
    }
    
    highlightSquare(col, row, color, alpha) {
        const x = this.margin + col * this.cellWidth;
        const y = this.margin + row * this.cellHeight;
        const size = Math.min(this.cellWidth, this.cellHeight) * 0.9;
        
        this.ctx.fillStyle = color;
        this.ctx.globalAlpha = alpha;
        this.ctx.fillRect(x - size/2, y - size/2, size, size);
        this.ctx.globalAlpha = 1.0;
    }
    
    setLastMove(moveStr) {
        if (moveStr && moveStr.length >= 4) {
            this.lastMove = {
                from: moveStr.substring(0, 2),
                to: moveStr.substring(2, 4)
            };
        }
    }
}

// 初始化应用
document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
});

function initializeApp() {
    // 初始化Socket.IO连接
    socket = io();
    
    // 初始化棋盘渲染器
    window.boardRenderer = new ChessBoardRenderer('chess-board');
    
    // 初始化滚动管理器
    battleLogManager = new ScrollContainerManager('battle-log');
    
    APIProfiles.init();
    // 绑定事件监听器
    bindEventListeners();

    // 按当前下拉选项同步显示名和 base_url
    updateModelSettings();
    
    // 初始化Socket事件
    initializeSocketEvents();
    
}

function bindEventListeners() {
    // 开始对战按钮
    document.getElementById('start-battle').addEventListener('click', startBattle);
    
    // 停止对战按钮
    document.getElementById('stop-battle').addEventListener('click', stopBattle);
    
    // 重置游戏按钮
    document.getElementById('reset-battle').addEventListener('click', resetBattle);

    const resumeBtn = document.getElementById('resume-battle');
    if (resumeBtn) {
        resumeBtn.addEventListener('click', resumeBattle);
    }
    
    // 模型选择变化
    document.getElementById('red-model').addEventListener('change', () => APIProfiles.select('red'));
    document.getElementById('black-model').addEventListener('change', () => APIProfiles.select('black'));
}

function initializeSocketEvents() {
    
    // 连接状态
    socket.on('connect', function() {
        updateConnectionStatus('已连接');
        
        // 连接成功后重新绑定事件监听器
        bindThinkingStreamEvent();
        // 刷新页面或断线重连后，从服务端恢复当前局面和按钮状态
        syncBattleState();
    });
    
    socket.on('disconnect', function() {
        updateConnectionStatus('连接断开（自动重连中）');
        if (gameState.isPlaying) {
            setNetworkStatus('页面与本地服务的连接断开，正在自动重连；恢复后会同步局面', 'is-retrying');
        }
    });

    socket.on('battle_state', function(state) {
        applyBattleState(state);
    });
    
    // 游戏事件
    socket.on('thinking', function(data) {
        showThinkingStatus(data.player, data.message);
    });
    
    // 初始绑定thinking_stream事件
    bindThinkingStreamEvent();
    
    socket.on('move_made', function(data) {
        handleMoveMade(data);
    });
    
    socket.on('game_over', function(data) {
        handleGameOver(data);
    });
    
    socket.on('game_error', function(data) {
        handleGameError(data);
    });

    socket.on('network_retry', function(data) {
        handleNetworkRetry(data);
    });

    socket.on('battle_paused', function(data) {
        handleBattlePaused(data);
    });
    
    // 添加通用事件监听器来捕获所有事件
    socket.onAny(function(eventName, ...args) {
    });
    
}

// 单独的函数来绑定thinking_stream事件
function bindThinkingStreamEvent() {
    
    // 移除之前的监听器（如果存在）
    socket.off('thinking_stream');
    
    // 新增：处理流式思考过程
    socket.on('thinking_stream', function(data) {
        
        // 确保数据格式正确
        if (!data || typeof data !== 'object') {
            console.error('thinking_stream数据格式错误:', data);
            return;
        }
        
        const thinkingBoxId = `${data.player}-thinking-process`;
        const thinkingBox = document.getElementById(thinkingBoxId);
        
        if (!thinkingBox) {
            console.error(`找不到思考区元素: ${thinkingBoxId}`);
            return;
        }
        
        if (data.is_complete) {
            // 思考完成，清理状态
            clearStreamingState(data.player);
            return;
        }
        
        // 流式添加思考内容
        if (data.content && data.content.length > 0) {
            // 检查是否已有内容容器，如果没有则创建
            let contentContainer = thinkingBox.querySelector('.thinking-content-stream');
            if (!contentContainer) {
                // 清空现有内容
                thinkingBox.innerHTML = '';
                // 创建新的内容容器
                contentContainer = document.createElement('div');
                contentContainer.className = 'thinking-content-stream';
                contentContainer.style.whiteSpace = 'pre-wrap';
                contentContainer.style.wordWrap = 'break-word';
                thinkingBox.appendChild(contentContainer);
            }
            
            // 直接追加内容，不添加时间戳和装饰样式
            contentContainer.textContent += data.content;
            
            // 自动滚动到底部
            thinkingBox.scrollTop = thinkingBox.scrollHeight;
        }
    });
    
}

function startBattle() {
    let redConfig, blackConfig;
    try {
        redConfig = getPlayerConfig('red');
        blackConfig = getPlayerConfig('black');
    } catch(e) { alert(e.message); return; }
    if ([redConfig, blackConfig].some(c => c.base_url.startsWith('http:')) &&
        !confirm('所选配置含 HTTP 地址。发往非本机服务时 key 会明文传输；本机 Ollama / LM Studio 通常可以继续。是否开始对战？')) return;
    
    if (!validateConfig(redConfig) || !validateConfig(blackConfig)) {
        alert('请填写完整的模型配置信息');
        return;
    }
    
    showLoading(true);
    gameState.canRetryNow = false;
    gameState.isPaused = false;
    gameState.lastGameOverKey = null;
    gameState.stopRequestedAt = 0;
    setNetworkStatus('', '');
    clearGameInfo();
    highlightWinner('');

    fetch('/api/start_battle', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            red_player: redConfig,
            black_player: blackConfig
        })
    })
    .then(response => response.json())
    .then(data => {
        showLoading(false);
        if (data.status === 'success') {
            gameState.startTime = new Date();
            const sameBattle = data.state && gameState.battleId === data.state.battle_id;
            if (!sameBattle) {
                // 这盘棋的实时事件还没到：先按开局状态显示
                gameState.isPlaying = true;
                gameState.isPaused = false;
                gameState.boardState = null;
                gameState.moveCount = 0;
                updateControlButtons(true);
                if (data.state) applyBattleState(data.state);
            }
            // 否则事件（网络重连/暂停/走子）已先到，以事件为准，不覆盖
        } else {
            alert('启动对战失败: ' + data.message);
        }
    })
    .catch(error => {
        showLoading(false);
        console.error('启动对战错误:', error);
        alert('启动对战时发生错误');
    });
}

function stopBattle() {
    gameState.stopRequestedAt = Date.now();
    // 先在页面上立即生效，再通知后端（后端会取消正在进行的模型请求和重连等待）
    gameState.isPlaying = false;
    gameState.isPaused = false;
    gameState.canRetryNow = false;
    updateGameStatus('对战已停止');
    setNetworkStatus('', '');
    updateControlButtons(false);
    hideThinkingStatus();
    fetch('/api/stop_battle', { method: 'POST' })
    .then(response => response.json())
    .then(data => {
        if (data.status !== 'success') {
            console.warn('停止对战返回:', data);
        } else if (data.state) {
            applyBattleState(data.state);
        }
    })
    .catch(error => {
        console.error('停止对战错误:', error);
        setNetworkStatus('连不上本地服务，请看终端里程序是否还在运行', '');
    });
}

function resetBattle() {
    if (!confirm('确定要重置游戏吗？这将停止当前对局并清空页面（已保存的棋谱文件不会删除）。')) {
        return;
    }
    fetch('/api/reset_battle', { method: 'POST' }).catch(error => console.error('重置对战错误:', error));
    resetLocalUI();
}

function resetLocalUI() {
    gameState = {
        isPlaying: false,
        isPaused: false,
        canRetryNow: false,
        currentPlayer: 'red',
        moveCount: 0,
        startTime: null,
        boardState: null
    };
    updateGameStatus('等待开始');
    setNetworkStatus('', '');
    updateControlButtons(false);
    clearGameInfo();
    boardRenderer.drawBoard();
    boardRenderer.showInitialPosition();
    updateCurrentPlayer('red');
    document.getElementById('current-round').textContent = '0';
    document.getElementById('total-moves').textContent = '0';
    document.getElementById('battle-duration').textContent = '00:00';
    const red = document.querySelector('.player-red');
    const black = document.querySelector('.player-black');
    if (red) red.classList.remove('winner-highlight');
    if (black) black.classList.remove('winner-highlight');
}

function getPlayerConfig(player) { return APIProfiles.config(player); }
function isLocalBase(url) {
    try {
        const host = new URL(url).hostname.replace(/^\[|\]$/g, '');
        return host === 'localhost' || host === '127.0.0.1' || host === '::1';
    } catch (_) { return false; }
}
function validateConfig(config) {
    return !!(config.model_name && config.display_name && (config.api_key || isLocalBase(config.base_url)));
}
function updateModelSettings() { /* APIProfiles 统一管理，初始化已完成。 */ }

function showThinkingStatus(player, message) {
    // 不显示任何思考状态信息
    return;
}

function hideThinkingStatus() {
    const redThinking = document.getElementById('red-thinking');
    const blackThinking = document.getElementById('black-thinking');
    if (redThinking) {
        redThinking.style.display = 'none';
    }
    if (blackThinking) {
        blackThinking.style.display = 'none';
    }
}

function handleMoveMade(data) {
    if (data.board_state) {
        boardRenderer.updateBoard(data.board_state);
        boardRenderer.setLastMove(data.move);
        gameState.boardState = data.board_state;
    }
    if (data.current_player) {
        updateCurrentPlayer(data.current_player);
        gameState.currentPlayer = data.current_player;
    }
    gameState.moveCount = data.move_count || 0;
    document.getElementById('total-moves').textContent = gameState.moveCount;
    document.getElementById('current-round').textContent = Math.ceil(gameState.moveCount / 2);
    // 走成功了，说明网络已恢复
    gameState.canRetryNow = false;
    setNetworkStatus('', '');
    updateControlButtons(gameState.isPlaying);
    addBattleLogEntry(`${data.player} 走了 ${data.move}${data.gives_check ? '（将军！）' : ''}`, 'move');
    updateBattleDuration();
}

function resultText(result) {
    if (!result) return '对局结束';
    if (typeof result === 'string') return result;
    return result.message || result.game_result || '对局结束';
}

function handleGameOver(data) {
    gameState.isPlaying = false;
    gameState.isPaused = false;
    gameState.canRetryNow = false;
    setNetworkStatus('', '');
    updateControlButtons(false);
    const result = (data && data.result) || {};
    const text = (data && data.message) || resultText(result);
    if (data && data.board_state) {
        boardRenderer.updateBoard(data.board_state);
    }
    updateGameStatus(`对局结束：${text}`);
    addBattleLogEntry(`对局结束：${text}`, 'system');
    try {
        highlightWinner((data && data.winner_color) || result.winner_color || '');
    } catch (e) {
        console.error('高亮获胜方失败:', e);
    }
    const key = (data && data.record_path) || text;
    if (gameState.lastGameOverKey !== key) {
        gameState.lastGameOverKey = key;
        // 稍等让棋盘先画完最后一步
        setTimeout(() => alert(`对局结束：${text}${data && data.record_path ? '\n棋谱已保存：' + data.record_path : ''}`), 300);
    }
}

function handleGameError(data) {
    console.error('中国象棋游戏错误:', data);
    let message = (data && data.message) ? String(data.message) : '未知错误';
    message = message.replace(/。?请严格按照「棋步：xxxx」格式回复[^。]*。?/g, '');
    updateGameStatus('对战出错：' + message);
    addBattleLogEntry('对战出错：' + message, 'system');
    // 状态以服务端为准（多数错误会转成可继续的暂停）
    syncBattleState();
}

function setNetworkStatus(text, kind) {
    const element = document.getElementById('network-status');
    if (!element) {
        return;
    }
    element.textContent = text || '';
    if (text) document.getElementById('network-details').open = true;
    element.className = 'network-status' + (kind ? ` ${kind}` : '');
}

function handleNetworkRetry(data) {
    const message = (data && data.message) ? data.message : '网络问题，正在重连';
    gameState.isPlaying = true;
    gameState.isPaused = false;
    gameState.canRetryNow = true;
    setNetworkStatus(message + (data && data.detail ? `：${data.detail}` : ''), 'is-retrying');
    updateGameStatus(message);
    updateControlButtons(true);
    addBattleLogEntry(message, 'system');
}

function handleBattlePaused(data) {
    gameState.isPlaying = false;
    gameState.isPaused = true;
    gameState.canRetryNow = false;
    const detail = (data && data.message) ? data.message : '连不上 API 服务器，请检查网络/代理（建议国内网站直连）';
    setNetworkStatus(detail, '');
    updateGameStatus('已暂停，点「继续对战」接着下');
    updateControlButtons(false);
    addBattleLogEntry(`对局已暂停。${detail}`, 'system');
}

// 用服务端快照恢复界面：页面刷新、socket 重连、定时轮询都走这里
function applyBattleState(state) {
    if (!state) return;
    // 丢弃过期快照（比已经收到的新状态更早），避免按钮被旧状态覆盖
    if (state.red_player && state.black_player) {
        document.getElementById('active-match').textContent = `红：${state.red_player.display_name} · 黑：${state.black_player.display_name}`;
    }
    if (state.battle_id) {
        if (gameState.battleId === state.battle_id && typeof state.seq === 'number' && state.seq < (gameState.lastSeq || 0)) {
            return;
        }
        // 刚点了停止：停止请求发出前的「进行中」快照不再采用
        if (gameState.stopRequestedAt && Date.now() - gameState.stopRequestedAt < 3000
            && gameState.battleId === state.battle_id && state.status === 'playing') {
            return;
        }
        if (gameState.battleId !== state.battle_id) {
            gameState.battleId = state.battle_id;
        }
        gameState.lastSeq = state.seq || 0;
    }
    if (state.status === 'no_battle') {
        if (gameState.isPlaying || gameState.isPaused) {
            gameState.isPlaying = false;
            gameState.isPaused = false;
            gameState.canRetryNow = false;
            updateControlButtons(false);
            setNetworkStatus('本地服务里没有正在进行的对局（可能重启过），请重新开始对战', '');
        }
        return;
    }
    if (state.board_state && state.board_state !== gameState.boardState) {
        boardRenderer.updateBoard(state.board_state);
        if (state.last_move) boardRenderer.setLastMove(state.last_move);
        gameState.boardState = state.board_state;
    }
    if (state.current_player) {
        updateCurrentPlayer(state.current_player);
        gameState.currentPlayer = state.current_player;
    }
    const restoringLog = (gameState.moveCount || 0) === 0 && (state.move_count || 0) > 0
        && battleLogManager && battleLogManager.container && !gameState.restoredLog;
    gameState.moveCount = state.move_count || 0;
    document.getElementById('total-moves').textContent = gameState.moveCount;
    document.getElementById('current-round').textContent = Math.ceil(gameState.moveCount / 2);
    if (restoringLog && Array.isArray(state.moves)) {
        gameState.restoredLog = true;
        addBattleLogEntry(`已恢复当前对局（${state.moves.length} 步）`, 'system');
        state.moves.forEach(m => addBattleLogEntry(`${m.player_name} 走了 ${m.move}`, 'move'));
    }
    if (!gameState.startTime && state.status !== 'finished') {
        gameState.startTime = new Date();
    }

    const phase = state.phase;
    if (state.status === 'finished') {
        if (gameState.lastGameOverKey !== (state.record_path || resultText(state.result))) {
            handleGameOver({ result: state.result, message: resultText(state.result),
                             winner_color: state.result && state.result.winner_color,
                             record_path: state.record_path, board_state: state.board_state });
        }
        return;
    }
    if (state.status === 'stopped') {
        gameState.isPlaying = false;
        gameState.isPaused = false;
        gameState.canRetryNow = false;
        updateControlButtons(false);
        updateGameStatus('对战已停止');
        return;
    }
    if (state.can_resume) {
        gameState.isPlaying = false;
        gameState.isPaused = true;
        gameState.canRetryNow = false;
        const why = state.stalled ? '对战线程已停止' : (state.pause_reason || '已暂停');
        setNetworkStatus(why.includes('继续对战') ? why : (why + '，点「继续对战」从当前局面接着下'), '');
        updateGameStatus('已暂停');
        updateControlButtons(false);
        return;
    }
    gameState.isPlaying = true;
    gameState.isPaused = false;
    const waited = (state.server_time && state.phase_since) ? (state.server_time - state.phase_since) : 0;
    // 网络重连中一律可点；等模型超过 90 秒也给按钮，免得干等
    gameState.canRetryNow = !!state.can_retry_now && (phase === 'network_retry' || waited > 90);
    if (phase === 'network_retry') {
        setNetworkStatus(state.phase_message || '网络问题，正在重连', 'is-retrying');
        updateGameStatus('网络重连中');
    } else if (phase === 'thinking') {
        const side = state.current_player === 'red' ? '红方' : '黑方';
        updateGameStatus(`等待${side}模型回复（${Math.round(waited)} 秒）${state.in_check ? '，正被将军' : ''}`);
        if (!gameState.canRetryNow) setNetworkStatus('', '');
    } else {
        updateGameStatus('对战进行中');
    }
    updateControlButtons(true);
}

function syncBattleState() {
    return fetch('/api/get_battle_status')
        .then(r => r.json())
        .then(state => { applyBattleState(state); gameState.serverReachable = true; return state; })
        .catch(err => {
            console.warn('获取对战状态失败:', err);
            if (gameState.isPlaying || gameState.isPaused) {
                gameState.serverReachable = false;
                setNetworkStatus('连不上本地象棋服务（终端里的程序可能停了），恢复后会自动同步', '');
            }
        });
}

function resumeBattle() {
    const resumeBtn = document.getElementById('resume-battle');
    if (resumeBtn) {
        resumeBtn.disabled = true;
    }
    const retryNow = gameState.canRetryNow && gameState.isPlaying;
    setNetworkStatus(retryNow ? '正在立即重试...' : '正在继续对局...', 'is-retrying');
    fetch('/api/resume_battle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            gameState.isPlaying = true;
            gameState.isPaused = false;
            gameState.canRetryNow = false;
            setNetworkStatus(data.action === 'retry_now' ? '已立即重试' : '已继续对局', 'is-ok');
            updateGameStatus('对战进行中');
            updateControlButtons(true);
            addBattleLogEntry(data.action === 'retry_now' ? '已立即重新请求当前一方' : '已从当前局面继续对局', 'system');
            if (data.state) applyBattleState(data.state);
        } else {
            alert('继续对局失败: ' + (data.message || '未知错误'));
            syncBattleState();
        }
    })
    .catch(error => {
        console.error('继续对局错误:', error);
        alert('继续对局时发生错误，请检查本地服务是否还在运行');
    })
    .finally(() => {
        if (resumeBtn) resumeBtn.disabled = false;
        updateControlButtons(gameState.isPlaying);
    });
}

function updateConnectionStatus(status) {
    const element = document.getElementById('connection-status');
    if (element) {
        element.textContent = `连接状态: ${status}`;
    }
}

function updateGameStatus(status) {
    const element = document.getElementById('game-status');
    if (element) {
        element.textContent = `游戏状态: ${status}`;
    }
}

function updateControlButtons(isPlaying) {
    APIProfiles.lock(isPlaying || !!gameState.isPaused);
    const paused = !!gameState.isPaused;
    const retry = !!gameState.canRetryNow && !!isPlaying;
    document.getElementById('start-battle').disabled = isPlaying || paused;
    document.getElementById('stop-battle').disabled = !isPlaying && !paused;
    const resumeBtn = document.getElementById('resume-battle');
    if (resumeBtn) {
        const show = paused || retry;
        resumeBtn.style.display = show ? 'inline-block' : 'none';
        resumeBtn.textContent = retry ? '立即重试' : '继续对战';
        resumeBtn.title = retry ? '不等倒计时，马上重新请求当前一方' : '从当前局面、轮到的一方接着下';
    }
}

function clearGameInfo() {
    // 清空思考过程
    const thinkingProcess = document.getElementById('thinking-process');
    if (thinkingProcess) {
        thinkingProcess.innerHTML = '';
    }
    
    // 清空棋谱历史
    const moveHistory = document.getElementById('move-history');
    if (moveHistory) {
        moveHistory.innerHTML = '';
    }
    
    // 清空对战日志 - 只保留简洁的棋步记录
    const battleLog = document.getElementById('battle-log');
    if (battleLog) {
        battleLog.innerHTML = '';
    }
    
    // 清空游戏结果
    const gameResult = document.getElementById('game-result');
    if (gameResult) {
        gameResult.innerHTML = '';
    }
    
    // 重置最后一步信息
    const lastMoveText = document.getElementById('last-move-text');
    if (lastMoveText) {
        lastMoveText.textContent = '';
    }
}

function updateMoveHistory(history) {
    // 不显示棋谱历史信息
    return;
}

// 滚动容器管理器
class ScrollContainerManager {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.isUserInteracting = false;
        this.autoScrollEnabled = true;
        this.scrollTimeout = null;
        this.interactionTimeout = null;
        this.lastScrollTop = 0;
        
        if (this.container) {
            this.initializeScrollBehavior();
        }
    }
    
    initializeScrollBehavior() {
        // 监听用户滚动交互
        this.container.addEventListener('scroll', () => {
            this.handleUserScroll();
        });
        
        // 监听鼠标进入/离开
        this.container.addEventListener('mouseenter', () => {
            this.handleMouseEnter();
        });
        
        this.container.addEventListener('mouseleave', () => {
            this.handleMouseLeave();
        });
        
        // 监听触摸事件（移动设备）
        this.container.addEventListener('touchstart', () => {
            this.handleUserInteraction();
        });
        
        this.container.addEventListener('touchend', () => {
            this.handleInteractionEnd();
        });
        
        // 监听鼠标滚轮事件
        this.container.addEventListener('wheel', () => {
            this.handleUserInteraction();
        });
    }
    
    handleUserScroll() {
        const currentScrollTop = this.container.scrollTop;
        const maxScrollTop = this.container.scrollHeight - this.container.clientHeight;
        
        // 检测用户是否主动向上滚动
        if (currentScrollTop < this.lastScrollTop && currentScrollTop < maxScrollTop - 10) {
            this.handleUserInteraction();
        }
        
        this.lastScrollTop = currentScrollTop;
    }
    
    handleMouseEnter() {
        // 鼠标进入时暂时禁用自动滚动
        this.isUserInteracting = true;
    }
    
    handleMouseLeave() {
        // 鼠标离开时延迟恢复自动滚动
        this.interactionTimeout = setTimeout(() => {
            this.isUserInteracting = false;
        }, 1000);
    }
    
    handleUserInteraction() {
        this.isUserInteracting = true;
        
        // 清除之前的超时
        if (this.interactionTimeout) {
            clearTimeout(this.interactionTimeout);
        }
        
        // 3秒后恢复自动滚动
        this.interactionTimeout = setTimeout(() => {
            this.isUserInteracting = false;
        }, 3000);
    }
    
    handleInteractionEnd() {
        // 触摸结束后1秒恢复自动滚动
        this.interactionTimeout = setTimeout(() => {
            this.isUserInteracting = false;
        }, 1000);
    }
    
    addContent(content, className = 'log-entry') {
        const entry = document.createElement('div');
        entry.className = className;
        entry.textContent = content;
        
        // 添加内容
        this.container.appendChild(entry);
        
        // 添加新内容指示器
        this.container.classList.add('has-new-content');
        setTimeout(() => {
            this.container.classList.remove('has-new-content');
        }, 2000);
        
        // 如果用户没有交互，则自动滚动
        if (!this.isUserInteracting && this.autoScrollEnabled) {
            this.smoothScrollToBottom();
        }
        
        return entry;
    }
    
    smoothScrollToBottom(duration = 300) {
        const start = this.container.scrollTop;
        const target = this.container.scrollHeight - this.container.clientHeight;
        const distance = target - start;
        const startTime = performance.now();
        
        const animateScroll = (currentTime) => {
            const elapsed = currentTime - startTime;
            const progress = Math.min(elapsed / duration, 1);
            
            // 使用缓动函数
            const easeOutCubic = 1 - Math.pow(1 - progress, 3);
            
            this.container.scrollTop = start + distance * easeOutCubic;
            
            if (progress < 1) {
                requestAnimationFrame(animateScroll);
            }
        };
        
        requestAnimationFrame(animateScroll);
    }
    
    clear() {
        this.container.innerHTML = '';
    }
    
    setAutoScroll(enabled) {
        this.autoScrollEnabled = enabled;
    }
}

// 全局滚动管理器实例
let battleLogManager = null;

function addBattleLogEntry(message, type = 'info') {
    // 显示棋步记录和关键系统提示（将军、网络重连、暂停、结束），过滤其他调试信息
    if (type !== 'move' && type !== 'system') {
        return;
    }
    
    // 初始化滚动管理器（如果还没有初始化）
    if (!battleLogManager) {
        battleLogManager = new ScrollContainerManager('battle-log');
    }
    
    const timestamp = new Date().toLocaleTimeString();
    const battleLog = document.getElementById('battle-log');
    
    // 如果是第一条记录，清空默认文本
    if (battleLog.innerHTML.includes('等待对战开始')) {
        battleLog.innerHTML = '';
    }
    
    // 使用滚动管理器添加内容
    const content = `${timestamp} ${message}`;
    battleLogManager.addContent(content, 'log-entry');
}

function highlightWinner(result) {
    // 根据结果高亮获胜方
    const redPlayerInfo = document.querySelector('.player-red');
    const blackPlayerInfo = document.querySelector('.player-black');
    
    if (redPlayerInfo) redPlayerInfo.classList.remove('winner-highlight');
    if (blackPlayerInfo) blackPlayerInfo.classList.remove('winner-highlight');
    
    const text = (typeof result === 'string') ? result : ((result && (result.winner_color || result.message)) || '');
    if (!redPlayerInfo || !blackPlayerInfo) return;
    if (text === 'red' || text.includes('红方获胜')) {
        redPlayerInfo.classList.add('winner-highlight');
    } else if (text === 'black' || text.includes('黑方获胜')) {
        blackPlayerInfo.classList.add('winner-highlight');
    }
}

function updateBattleDuration() {
    if (!gameState.startTime) return;
    
    const duration = Date.now() - gameState.startTime;
    document.getElementById('battle-duration').textContent = formatDuration(duration);
}

function formatDuration(milliseconds) {
    const seconds = Math.floor(milliseconds / 1000);
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    
    return `${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
}

function showLoading(show) {
    const loadingOverlay = document.getElementById('loading-overlay');
    loadingOverlay.style.display = show ? 'flex' : 'none';
}

// 兜底轮询：即使漏掉了 socket 事件，也能在几秒内显示正确的状态和按钮
setInterval(() => {
    if (document.hidden) return;
    if (gameState.isPlaying || gameState.isPaused || gameState.serverReachable === false) {
        syncBattleState();
    }
}, 4000);

// 定时更新对战时长
setInterval(() => {
    if (gameState.isPlaying && gameState.startTime) {
        updateBattleDuration();
    }
}, 1000);

// 页面卸载时断开Socket连接
window.addEventListener('beforeunload', function() {
    if (socket) {
        socket.disconnect();
    }
});
