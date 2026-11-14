import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  LineSeries,
  createChart,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { getDesktopApi } from "../services/desktopApi";

interface CandleData {
  time: string;
  open: string;
  high: string;
  low: string;
  close: string;
}

interface LinePoint {
  time: string;
  value: string;
}

interface CandleResponse {
  candles: CandleData[];
  fast_ema: LinePoint[];
  slow_ema: LinePoint[];
  rsi: LinePoint[];
  latest_price: string | null;
  latest_time: string | null;
}

/**
 * The engine returns ISO timestamps ("2026-11-13T07:05:00Z") but
 * lightweight-charts only accepts numeric UTC timestamps (or plain
 * "YYYY-MM-DD" strings) — anything else throws inside setData, which
 * surfaced as "Failed to load candle data. Retrying…" forever.
 */
function toChartTime(iso: string): UTCTimestamp {
  return Math.floor(new Date(iso).getTime() / 1000) as UTCTimestamp;
}

export function CandleChart({ timeframe = "5m" }: { timeframe?: string }) {
  const api = getDesktopApi();
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [latestPrice, setLatestPrice] = useState<string | null>(null);
  const [latestTime, setLatestTime] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!api || !containerRef.current) {
      return;
    }
    let cancelled = false;
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 300,
      layout: { background: { color: "#1a1f2b" }, textColor: "#8b93a7" },
      grid: {
        vertLines: { color: "#262d3d" },
        horzLines: { color: "#262d3d" },
      },
      timeScale: { timeVisible: true, secondsVisible: false },
    });
    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#3fb984",
      downColor: "#e06060",
      borderVisible: false,
      wickUpColor: "#3fb984",
      wickDownColor: "#e06060",
    });
    const fastSeries = chart.addSeries(LineSeries, {
      color: "#4f8cff",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const slowSeries = chart.addSeries(LineSeries, {
      color: "#e5b45c",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    const fetchData = (): void => {
      void api
        .getCandles(timeframe)
        .then((response) => {
          if (cancelled) return;
          if (!response || response.status !== 200) {
            setError("No candle data available yet.");
            return;
          }
          const body = response.body as CandleResponse;
          if (!body.candles || body.candles.length === 0) {
            setError("No candle data available yet. The live feed needs time to collect candles.");
            return;
          }
          setError(null);
          setLatestPrice(body.latest_price);
          setLatestTime(body.latest_time);
          candleSeries.setData(
            body.candles.map((c) => ({
              time: toChartTime(c.time),
              open: Number(c.open),
              high: Number(c.high),
              low: Number(c.low),
              close: Number(c.close),
            })),
          );
          fastSeries.setData(
            body.fast_ema.map((p) => ({ time: toChartTime(p.time), value: Number(p.value) })),
          );
          slowSeries.setData(
            body.slow_ema.map((p) => ({ time: toChartTime(p.time), value: Number(p.value) })),
          );
          chart.timeScale().fitContent();
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          const message = err instanceof Error ? err.message : String(err);
          setError(`Failed to load candle data: ${message} Retrying…`);
        });
    };
    fetchData();
    const retryTimer = setInterval(fetchData, 15000);

    const resizeObserver = new ResizeObserver((entries) => {
      if (entries.length > 0 && containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      cancelled = true;
      clearInterval(retryTimer);
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [api, timeframe]);

  return (
    <div>
      {latestPrice && (
        <p className="meta chart-price">
          BTC-USD: <b>{latestPrice}</b>
          {latestTime && ` · as of ${latestTime.replace("T", " ").slice(0, 16)} UTC`}
        </p>
      )}
      <div ref={containerRef} className="chart-container" />
      {error && (
        <p className="meta">{error}</p>
      )}
    </div>
  );
}
