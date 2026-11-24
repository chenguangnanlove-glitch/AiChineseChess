/* 15×15 五子棋棋盘。列 A–O 从左到右，行 1–15 从上到下。 */
(function () {
    const COLS = 'ABCDEFGHIJKLMNO';

    class GomokuBoardRenderer {
        constructor(canvas) {
            this.canvas = canvas;
            this.ctx = canvas.getContext('2d');
            this.size = 15;
            this.margin = 28;
            this.boardSpan = 540;
            this.lastMove = null;
            this.boardState = null;
            this.mount();
        }

        mount() {
            this.canvas.width = this.boardSpan + this.margin * 2;
            this.canvas.height = this.boardSpan + this.margin * 2;
            this.cell = this.boardSpan / (this.size - 1);
            this.canvas.classList.add('gomoku-canvas');
            this.canvas.setAttribute('aria-label', '五子棋棋盘，15 路，无禁手');
            if (this.boardState) this.updateBoard(this.boardState);
            else this.showInitialPosition();
        }

        showInitialPosition() {
            this.lastMove = null;
            this.updateBoard(new Array(15).fill('...............').join('/'));
        }

        updateBoard(boardState) {
            if (!boardState) return;
            this.boardState = boardState;
            const ctx = this.ctx;
            const { margin, cell, size } = this;
            ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
            ctx.fillStyle = '#e7c48a';
            ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
            ctx.strokeStyle = '#6b4a2b';
            ctx.lineWidth = 3;
            ctx.strokeRect(8, 8, this.canvas.width - 16, this.canvas.height - 16);
            ctx.strokeStyle = '#3a2a1c';
            ctx.lineWidth = 1.2;
            for (let i = 0; i < size; i++) {
                ctx.beginPath();
                ctx.moveTo(margin, margin + i * cell);
                ctx.lineTo(margin + (size - 1) * cell, margin + i * cell);
                ctx.stroke();
                ctx.beginPath();
                ctx.moveTo(margin + i * cell, margin);
                ctx.lineTo(margin + i * cell, margin + (size - 1) * cell);
                ctx.stroke();
            }
            [[3, 3], [3, 11], [7, 7], [11, 3], [11, 11]].forEach(([c, r]) => {
                ctx.beginPath();
                ctx.arc(margin + c * cell, margin + r * cell, 3.2, 0, Math.PI * 2);
                ctx.fillStyle = '#3a2a1c';
                ctx.fill();
            });
            ctx.fillStyle = '#6b4a2b';
            ctx.font = '12px sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            for (let i = 0; i < size; i++) {
                ctx.fillText(COLS[i], margin + i * cell, 14);
                ctx.fillText(String(i + 1), 14, margin + i * cell);
            }
            const rows = boardState.split('/');
            for (let r = 0; r < size; r++) {
                const line = rows[r] || '';
                for (let c = 0; c < size; c++) {
                    const stone = line[c];
                    if (stone === 'X' || stone === 'O') this.drawStone(c, r, stone === 'X' ? 'black' : 'white');
                }
            }
            if (this.lastMove) {
                const pos = this.coordToPos(this.lastMove);
                if (pos) {
                    ctx.beginPath();
                    ctx.arc(margin + pos.col * cell, margin + pos.row * cell, 4, 0, Math.PI * 2);
                    ctx.fillStyle = '#d23b3b';
                    ctx.fill();
                }
            }
        }

        drawStone(col, row, color) {
            const x = this.margin + col * this.cell;
            const y = this.margin + row * this.cell;
            const radius = this.cell * 0.38;
            this.ctx.beginPath();
            this.ctx.arc(x + 1, y + 1, radius, 0, Math.PI * 2);
            this.ctx.fillStyle = 'rgba(0,0,0,0.18)';
            this.ctx.fill();
            this.ctx.beginPath();
            this.ctx.arc(x, y, radius, 0, Math.PI * 2);
            this.ctx.fillStyle = color === 'black' ? '#1c1c1c' : '#f7f4ee';
            this.ctx.fill();
            this.ctx.lineWidth = 1;
            this.ctx.strokeStyle = color === 'black' ? '#111' : '#b7aa98';
            this.ctx.stroke();
        }

        coordToPos(move) {
            const match = /^([A-O])(1[0-5]|[1-9])$/i.exec(String(move || '').replace(/\s+/g, ''));
            if (!match) return null;
            return { col: match[1].toUpperCase().charCodeAt(0) - 65, row: parseInt(match[2], 10) - 1 };
        }

        setLastMove(move) {
            this.lastMove = move || null;
            if (this.boardState) this.updateBoard(this.boardState);
        }

        cellFromEvent(ev) {
            const rect = this.canvas.getBoundingClientRect();
            const scaleX = this.canvas.width / (rect.width || this.canvas.width);
            const scaleY = this.canvas.height / (rect.height || this.canvas.height);
            const x = (ev.clientX - rect.left) * scaleX;
            const y = (ev.clientY - rect.top) * scaleY;
            const col = Math.round((x - this.margin) / this.cell);
            const row = Math.round((y - this.margin) / this.cell);
            if (col < 0 || col > 14 || row < 0 || row > 14) return null;
            const cx = this.margin + col * this.cell;
            const cy = this.margin + row * this.cell;
            const dx = x - cx;
            const dy = y - cy;
            if (dx * dx + dy * dy > (this.cell * 0.48) * (this.cell * 0.48)) return null;
            return { col, row, move: COLS[col] + String(row + 1) };
        }
    }

    window.GomokuBoardRenderer = GomokuBoardRenderer;
})();
