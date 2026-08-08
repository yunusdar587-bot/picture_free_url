/**
 * 图表画线工具：线段、射线、矩形、斐波那契回撤。
 *
 * 画在覆盖于图表之上的一张 canvas 上。每个端点存的不是像素，而是
 * “某根 K 线 + 相对它的偏移 + 价格”，每帧再换算回像素，
 * 所以缩放、平移、换时间区间之后图形仍然贴着原来的位置。
 */
(function (global) {
  "use strict";

  const HIT_TOLERANCE = 8;   // 命中判定的像素半径：线只有一两个像素宽，得留点余量
  const HANDLE_RADIUS = 4;
  const DRAG_THRESHOLD = 4;  // 小于这个位移算“点击”，进入点-点模式
  const MAX_HISTORY = 200;
  const SEPARATOR_HEIGHT = 1;

  const ACCENT = "#2962ff";
  const SELECTED = "#5b8dff";

  // 与 TradingView 默认回撤位一致
  const FIB_LEVELS = [
    { value: 0, color: "#787b86" },
    { value: 0.236, color: "#f23645" },
    { value: 0.382, color: "#ff9800" },
    { value: 0.5, color: "#4caf50" },
    { value: 0.618, color: "#089981" },
    { value: 0.786, color: "#00bcd4" },
    { value: 1, color: "#787b86" },
  ];

  const POINT_COUNT = { trendline: 2, ray: 2, rectangle: 2, fib: 2 };

  function distToSegment(px, py, x1, y1, x2, y2) {
    const dx = x2 - x1;
    const dy = y2 - y1;
    const lenSq = dx * dx + dy * dy;
    let t = lenSq === 0 ? 0 : ((px - x1) * dx + (py - y1) * dy) / lenSq;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
  }

  function distToRay(px, py, x1, y1, x2, y2) {
    const dx = x2 - x1;
    const dy = y2 - y1;
    const lenSq = dx * dx + dy * dy;
    // 射线只向 p1→p2 一侧延伸，所以 t 只在下方截断
    const t = lenSq === 0 ? 0 : Math.max(0, ((px - x1) * dx + (py - y1) * dy) / lenSq);
    return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
  }

  function withAlpha(hex, alpha) {
    const value = parseInt(hex.slice(1), 16);
    const r = (value >> 16) & 255;
    const g = (value >> 8) & 255;
    const b = value & 255;
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  function clonePoints(points) {
    return points.map((p) => ({ time: p.time, offset: p.offset, price: p.price }));
  }

  function cloneDrawings(list) {
    return list.map((d) => ({ id: d.id, type: d.type, points: clonePoints(d.points) }));
  }

  /**
   * @param {object} options
   * @param {object} options.chart        IChartApi
   * @param {object} options.series       画在哪个序列的价格坐标上（K 线序列）
   * @param {HTMLElement} options.container  图表容器，覆盖层加在它里面
   * @param {number} [options.paneIndex]  该序列所在画板序号
   * @param {function} [options.formatPrice]
   * @param {function} [options.onChange] 状态变化回调，用来刷新按钮
   */
  function createDrawingTools(options) {
    const chart = options.chart;
    const series = options.series;
    const container = options.container;
    const paneIndex = options.paneIndex || 0;
    const formatPrice = options.formatPrice || ((v) => v.toFixed(2));
    const onChange = options.onChange || function () {};

    const canvas = document.createElement("canvas");
    canvas.className = "drawing-overlay";
    canvas.style.position = "absolute";
    canvas.style.left = "0";
    canvas.style.top = "0";
    canvas.style.pointerEvents = "none";  // 事件在容器上捕获，覆盖层只负责画
    canvas.style.zIndex = "3";
    container.appendChild(canvas);
    const ctx = canvas.getContext("2d");

    const books = new Map();  // 股票代码 -> 该股票的图形与历史
    let symbol = "";
    let times = [];           // 已加载 K 线的日期，升序
    let timeIndex = new Map();

    let tool = "cursor";
    let selectedId = null;
    let hoverId = null;
    let pending = null;   // 正在画：{ type, p1, downX, downY }
    let cursorPos = null;
    let drag = null;
    let blockMouseDown = false;
    let nextId = 1;
    let dirty = true;
    let lastSignature = "";

    function book() {
      let entry = books.get(symbol);
      if (!entry) {
        entry = { drawings: [], undo: [], redo: [] };
        books.set(symbol, entry);
      }
      return entry;
    }

    function emit() {
      const entry = book();
      onChange({
        tool,
        canUndo: entry.undo.length > 0,
        canRedo: entry.redo.length > 0,
        count: entry.drawings.length,
        hasSelection: selectedId !== null,
        drawing: pending !== null,
      });
    }

    function pushHistory(snapshot) {
      const entry = book();
      entry.undo.push(snapshot || cloneDrawings(entry.drawings));
      if (entry.undo.length > MAX_HISTORY) entry.undo.shift();
      entry.redo.length = 0;
    }

    // ---- 坐标换算 ---------------------------------------------------------

    function indexOfTime(time) {
      if (!times.length) return 0;
      const exact = timeIndex.get(time);
      if (exact !== undefined) return exact;
      // 换了时间区间后原来的那天可能不在数据里，退而求其次找最近的一天
      let lo = 0;
      let hi = times.length - 1;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (times[mid] < time) lo = mid + 1;
        else hi = mid;
      }
      return lo;
    }

    function toLogical(point) {
      if (point.time === null) return point.offset;
      return indexOfTime(point.time) + point.offset;
    }

    function makePoint(logical, price) {
      if (!times.length) return { time: null, offset: logical, price };
      const idx = Math.max(0, Math.min(times.length - 1, Math.round(logical)));
      return { time: times[idx], offset: logical - idx, price };
    }

    function paneGeometry() {
      const panes = chart.panes();
      let top = 0;
      let height = container.clientHeight;
      for (const pane of panes) {
        if (pane.paneIndex() === paneIndex) {
          height = pane.getHeight();
          break;
        }
        top += pane.getHeight() + SEPARATOR_HEIGHT;
      }
      const axisWidth = series.priceScale().width();
      return { top, height, width: Math.max(0, container.clientWidth - axisWidth) };
    }

    /** 鼠标位置换成画板内坐标；inPane 为假表示落在价格轴、时间轴或别的画板上。 */
    function localPos(event) {
      const rect = container.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      const geo = paneGeometry();
      const paneY = y - geo.top;
      return {
        x,
        y: paneY,
        inPane: x >= 0 && x <= geo.width && paneY >= 0 && paneY <= geo.height,
      };
    }

    function posToPoint(pos) {
      const logical = chart.timeScale().coordinateToLogical(pos.x);
      const price = series.coordinateToPrice(pos.y);
      if (logical === null || price === null) return null;
      return makePoint(logical, price);
    }

    /** 端点 -> 画板内像素坐标，取不到（没有数据等）时返回 null。 */
    function pointToXY(point) {
      const x = chart.timeScale().logicalToCoordinate(toLogical(point));
      const y = series.priceToCoordinate(point.price);
      if (x === null || y === null) return null;
      return { x, y };
    }

    function screenPoints(drawing) {
      const result = [];
      for (const point of drawing.points) {
        const xy = pointToXY(point);
        if (!xy) return null;
        result.push(xy);
      }
      return result;
    }

    // ---- 绘制 -------------------------------------------------------------

    function fibPrice(points, level) {
      // 与 TradingView 一致：先点的那头是 1，后点的那头是 0
      return points[1].price + (points[0].price - points[1].price) * level;
    }

    function drawTrendline(pts) {
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      ctx.lineTo(pts[1].x, pts[1].y);
      ctx.stroke();
    }

    function drawRay(pts, geo) {
      const dx = pts[1].x - pts[0].x;
      const dy = pts[1].y - pts[0].y;
      const len = Math.hypot(dx, dy);
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      if (len === 0) {
        ctx.lineTo(pts[1].x, pts[1].y);
      } else {
        const far = (geo.width + geo.height) * 2 / len;
        ctx.lineTo(pts[0].x + dx * far, pts[0].y + dy * far);
      }
      ctx.stroke();
    }

    function drawRectangle(pts) {
      const x = Math.min(pts[0].x, pts[1].x);
      const y = Math.min(pts[0].y, pts[1].y);
      ctx.strokeRect(x, y, Math.abs(pts[1].x - pts[0].x), Math.abs(pts[1].y - pts[0].y));
    }

    function drawFib(drawing, pts, geo) {
      const left = Math.min(pts[0].x, pts[1].x);
      const right = Math.max(pts[0].x, pts[1].x);
      const levelY = FIB_LEVELS.map((level) => {
        const y = series.priceToCoordinate(fibPrice(drawing.points, level.value));
        return y === null ? null : y;
      });

      // 相邻两档之间铺一层淡色，方便一眼看出区间
      for (let i = 0; i < FIB_LEVELS.length - 1; i += 1) {
        if (levelY[i] === null || levelY[i + 1] === null) continue;
        ctx.fillStyle = withAlpha(FIB_LEVELS[i + 1].color, 0.08);
        ctx.fillRect(left, levelY[i], right - left, levelY[i + 1] - levelY[i]);
      }

      const dash = ctx.getLineDash();
      ctx.save();
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = withAlpha("#787b86", 0.9);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      ctx.lineTo(pts[1].x, pts[1].y);
      ctx.stroke();
      ctx.restore();
      ctx.setLineDash(dash);

      ctx.font = "11px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
      ctx.textBaseline = "bottom";
      for (let i = 0; i < FIB_LEVELS.length; i += 1) {
        const y = levelY[i];
        if (y === null) continue;
        const level = FIB_LEVELS[i];
        ctx.strokeStyle = level.color;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(left, y);
        ctx.lineTo(right, y);
        ctx.stroke();

        ctx.fillStyle = level.color;
        const price = fibPrice(drawing.points, level.value);
        ctx.fillText(`${level.value.toFixed(3)} (${formatPrice(price)})`, left + 4, y - 2);
      }
    }

    function drawHandles(pts) {
      for (const p of pts) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, HANDLE_RADIUS, 0, Math.PI * 2);
        ctx.fillStyle = "#ffffff";
        ctx.fill();
        ctx.lineWidth = 2;
        ctx.strokeStyle = ACCENT;
        ctx.stroke();
      }
    }

    function drawShape(drawing, geo, state) {
      const pts = screenPoints(drawing);
      if (!pts) return;

      ctx.save();
      ctx.strokeStyle = state.selected || state.hovered ? SELECTED : ACCENT;
      ctx.lineWidth = state.selected || state.hovered ? 2.5 : 1.5;
      ctx.globalAlpha = state.preview ? 0.85 : 1;

      if (drawing.type === "trendline") drawTrendline(pts);
      else if (drawing.type === "ray") drawRay(pts, geo);
      else if (drawing.type === "rectangle") drawRectangle(pts);
      else if (drawing.type === "fib") drawFib(drawing, pts, geo);

      ctx.restore();
      if (state.selected) drawHandles(pts);
    }

    function previewDrawing() {
      if (!pending || !cursorPos) return null;
      const p2 = posToPoint(cursorPos);
      if (!p2) return null;
      return { id: -1, type: pending.type, points: [pending.p1, p2] };
    }

    function render() {
      const width = container.clientWidth;
      const height = container.clientHeight;
      const dpr = global.devicePixelRatio || 1;
      if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
      }
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);

      const geo = paneGeometry();
      ctx.save();
      // 图形不许溢出到成交量画板和价格轴上
      ctx.beginPath();
      ctx.rect(0, geo.top, geo.width, geo.height);
      ctx.clip();
      ctx.translate(0, geo.top);

      for (const drawing of book().drawings) {
        drawShape(drawing, geo, {
          selected: drawing.id === selectedId,
          hovered: drawing.id === hoverId,
        });
      }
      const preview = previewDrawing();
      if (preview) drawShape(preview, geo, { preview: true });
      ctx.restore();
    }

    /** 图表自己缩放/平移时不发通知，只能每帧比对一下坐标有没有变。 */
    function signature() {
      const range = chart.timeScale().getVisibleLogicalRange();
      const geo = paneGeometry();
      return [
        range ? range.from : "",
        range ? range.to : "",
        series.coordinateToPrice(0),
        series.coordinateToPrice(100),
        geo.top,
        geo.height,
        geo.width,
        container.clientHeight,
      ].join("|");
    }

    function frame() {
      const sig = signature();
      if (dirty || sig !== lastSignature) {
        lastSignature = sig;
        dirty = false;
        render();
      }
      global.requestAnimationFrame(frame);
    }

    // ---- 命中判定 ---------------------------------------------------------

    function hitDrawing(drawing, pos) {
      const pts = screenPoints(drawing);
      if (!pts) return null;

      for (let i = 0; i < pts.length; i += 1) {
        if (Math.hypot(pos.x - pts[i].x, pos.y - pts[i].y) <= HANDLE_RADIUS + HIT_TOLERANCE / 2) {
          return { drawing, kind: "handle", index: i };
        }
      }

      let hit = false;
      if (drawing.type === "trendline") {
        hit = distToSegment(pos.x, pos.y, pts[0].x, pts[0].y, pts[1].x, pts[1].y) <= HIT_TOLERANCE;
      } else if (drawing.type === "ray") {
        hit = distToRay(pos.x, pos.y, pts[0].x, pts[0].y, pts[1].x, pts[1].y) <= HIT_TOLERANCE;
      } else if (drawing.type === "rectangle") {
        const x1 = Math.min(pts[0].x, pts[1].x);
        const x2 = Math.max(pts[0].x, pts[1].x);
        const y1 = Math.min(pts[0].y, pts[1].y);
        const y2 = Math.max(pts[0].y, pts[1].y);
        const edges = [
          [x1, y1, x2, y1],
          [x2, y1, x2, y2],
          [x2, y2, x1, y2],
          [x1, y2, x1, y1],
        ];
        hit = edges.some((e) => distToSegment(pos.x, pos.y, e[0], e[1], e[2], e[3]) <= HIT_TOLERANCE);
      } else if (drawing.type === "fib") {
        const left = Math.min(pts[0].x, pts[1].x);
        const right = Math.max(pts[0].x, pts[1].x);
        hit = distToSegment(pos.x, pos.y, pts[0].x, pts[0].y, pts[1].x, pts[1].y) <= HIT_TOLERANCE;
        if (!hit) {
          hit = FIB_LEVELS.some((level) => {
            const y = series.priceToCoordinate(fibPrice(drawing.points, level.value));
            return y !== null && distToSegment(pos.x, pos.y, left, y, right, y) <= HIT_TOLERANCE;
          });
        }
      }
      return hit ? { drawing, kind: "shape", index: -1 } : null;
    }

    function hitAt(pos) {
      const list = book().drawings;
      for (let i = list.length - 1; i >= 0; i -= 1) {  // 后画的在上面
        const hit = hitDrawing(list[i], pos);
        if (hit) return hit;
      }
      return null;
    }

    // ---- 交互 -------------------------------------------------------------

    function commit(type, p1, p2) {
      pushHistory();
      const drawing = { id: nextId++, type, points: [p1, p2] };
      book().drawings.push(drawing);
      selectedId = drawing.id;
      setTool("cursor");  // 和 TradingView 一样，画完自动回到选择状态
      dirty = true;
      emit();
    }

    function onPointerDown(event) {
      blockMouseDown = false;
      if (event.button !== 0 || event.pointerType === "touch") return;
      const pos = localPos(event);
      if (!pos.inPane) return;

      if (tool !== "cursor") {
        const point = posToPoint(pos);
        if (!point) return;
        blockMouseDown = true;
        event.preventDefault();
        event.stopPropagation();
        if (!pending) {
          pending = { type: tool, p1: point, downX: pos.x, downY: pos.y };
        } else {
          commit(pending.type, pending.p1, point);  // 点-移动-再点
          pending = null;
        }
        cursorPos = pos;
        dirty = true;
        emit();
        return;
      }

      const hit = hitAt(pos);
      if (!hit) {
        if (selectedId !== null) {
          selectedId = null;
          dirty = true;
          emit();
        }
        return;  // 没点到图形就把事件让给图表，照常平移
      }

      blockMouseDown = true;
      event.preventDefault();
      event.stopPropagation();
      selectedId = hit.drawing.id;
      drag = {
        hit,
        startX: pos.x,
        startY: pos.y,
        startLogical: chart.timeScale().coordinateToLogical(pos.x),
        startPrice: series.coordinateToPrice(pos.y),
        origin: hit.drawing.points.map((p) => ({ logical: toLogical(p), price: p.price })),
        snapshot: cloneDrawings(book().drawings),
        moved: false,
      };
      dirty = true;
      emit();
    }

    function applyDrag(pos) {
      const logical = chart.timeScale().coordinateToLogical(pos.x);
      const price = series.coordinateToPrice(pos.y);
      if (logical === null || price === null) return;
      if (drag.startLogical === null || drag.startPrice === null) return;

      const points = drag.hit.drawing.points;
      if (drag.hit.kind === "handle") {
        points[drag.hit.index] = makePoint(logical, price);
      } else {
        const dLogical = logical - drag.startLogical;
        const dPrice = price - drag.startPrice;
        for (let i = 0; i < points.length; i += 1) {
          points[i] = makePoint(drag.origin[i].logical + dLogical, drag.origin[i].price + dPrice);
        }
      }
      dirty = true;
    }

    function onPointerMove(event) {
      const pos = localPos(event);
      cursorPos = pos;

      if (drag) {
        if (!drag.moved && Math.hypot(pos.x - drag.startX, pos.y - drag.startY) > 1) {
          drag.moved = true;
        }
        applyDrag(pos);
        return;
      }

      if (pending) {
        dirty = true;
        return;
      }

      if (tool === "cursor") {
        const hit = pos.inPane ? hitAt(pos) : null;
        const id = hit ? hit.drawing.id : null;
        if (id !== hoverId) {
          hoverId = id;
          container.classList.toggle("drawing-hit", id !== null);
          dirty = true;
        }
      }
    }

    function onPointerUp(event) {
      if (drag) {
        if (drag.moved) {
          pushHistory(drag.snapshot);
        }
        drag = null;
        dirty = true;
        emit();
        return;
      }
      if (!pending) return;

      const pos = localPos(event);
      // 按下后拖出一段再松手就直接成形；原地松手则等下一次点击
      if (Math.hypot(pos.x - pending.downX, pos.y - pending.downY) > DRAG_THRESHOLD) {
        const point = posToPoint(pos);
        if (point) {
          commit(pending.type, pending.p1, point);
          pending = null;
        }
      }
    }

    function onKeyDown(event) {
      const target = event.target;
      if (target && (target.tagName === "INPUT" || target.tagName === "SELECT" ||
          target.tagName === "TEXTAREA" || target.isContentEditable)) {
        return;
      }
      const mod = event.ctrlKey || event.metaKey;
      const key = event.key.toLowerCase();

      if (mod && key === "z") {
        event.preventDefault();
        if (event.shiftKey) redo(); else undo();
      } else if (mod && key === "y") {
        event.preventDefault();
        redo();
      } else if (event.key === "Escape") {
        cancel();
      } else if (event.key === "Delete" || event.key === "Backspace") {
        if (selectedId !== null) {
          event.preventDefault();
          deleteSelected();
        }
      }
    }

    // ---- 对外接口 ---------------------------------------------------------

    function setTool(name) {
      if (tool === name) return;
      tool = name;
      pending = null;
      container.classList.toggle("drawing-active", name !== "cursor");
      if (name !== "cursor") {
        selectedId = null;
        hoverId = null;
        container.classList.remove("drawing-hit");
      }
      dirty = true;
      emit();
    }

    function cancel() {
      if (pending) {
        pending = null;
        dirty = true;
      }
      if (tool !== "cursor") setTool("cursor");
      else if (selectedId !== null) {
        selectedId = null;
        dirty = true;
      }
      emit();
    }

    function undo() {
      const entry = book();
      if (!entry.undo.length) return;
      entry.redo.push(cloneDrawings(entry.drawings));
      entry.drawings = entry.undo.pop();
      if (!entry.drawings.some((d) => d.id === selectedId)) selectedId = null;
      pending = null;
      dirty = true;
      emit();
    }

    function redo() {
      const entry = book();
      if (!entry.redo.length) return;
      entry.undo.push(cloneDrawings(entry.drawings));
      entry.drawings = entry.redo.pop();
      if (!entry.drawings.some((d) => d.id === selectedId)) selectedId = null;
      pending = null;
      dirty = true;
      emit();
    }

    function deleteSelected() {
      const entry = book();
      const index = entry.drawings.findIndex((d) => d.id === selectedId);
      if (index < 0) return;
      pushHistory();
      entry.drawings.splice(index, 1);
      selectedId = null;
      dirty = true;
      emit();
    }

    function clearAll() {
      const entry = book();
      if (!entry.drawings.length) return;
      pushHistory();
      entry.drawings = [];
      selectedId = null;
      pending = null;
      dirty = true;
      emit();
    }

    /** 换股票：每只股票各存各的图形，切回来还在。 */
    function setSymbol(code) {
      if (symbol === code) return;
      symbol = code;
      selectedId = null;
      hoverId = null;
      pending = null;
      dirty = true;
      emit();
    }

    function setTimes(list) {
      times = list;
      timeIndex = new Map(list.map((t, i) => [t, i]));
      dirty = true;
    }

    container.addEventListener("pointerdown", onPointerDown, true);
    // 图表内部监听的是 mousedown；pointerdown 被拦下后它照样能收到，
    // 所以这里补一刀，免得画线时图表跟着平移。
    container.addEventListener("mousedown", (event) => {
      if (!blockMouseDown) return;
      event.preventDefault();
      event.stopPropagation();
    }, true);
    global.addEventListener("pointermove", onPointerMove);
    global.addEventListener("pointerup", onPointerUp);
    global.addEventListener("keydown", onKeyDown);
    global.requestAnimationFrame(frame);
    emit();

    return {
      setTool,
      getTool: () => tool,
      setSymbol,
      setTimes,
      undo,
      redo,
      clearAll,
      deleteSelected,
      cancel,
      invalidate: () => { dirty = true; },
    };
  }

  global.createDrawingTools = createDrawingTools;
})(window);
