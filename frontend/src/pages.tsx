import { useMemo, useState } from "react";
import { useAuctionData, useAuctionEvents, useAuctions } from "./hooks";
import { USE_MOCKS } from "./api";
import { AuctionSelector } from "./components/AuctionSelector";
import { EffectsBadges } from "./components/EffectsBadges";
import { ServerStatus } from "./components/ServerStatus";

function AuctionWorkspace({ compact = false }: { compact?: boolean }) {
  const [channel, setChannel] = useState("demo_streamer");
  const [selectedAuction, setSelectedAuction] = useState<number>();
  const auctionsQuery = useAuctions(channel);
  const auctions = auctionsQuery.data ?? [];

  const currentAuction = useMemo(
    () => auctions.find((auction) => auction.id === selectedAuction),
    [auctions, selectedAuction],
  );

  const { positions, activity, context, effects } = useAuctionData(selectedAuction);
  useAuctionEvents(selectedAuction);

  return (
    <section className={compact ? "workspace compact" : "workspace"}>
      <div className="controls">
        <label className="field">
          Канал
          <input value={channel} onChange={(event) => setChannel(event.target.value)} placeholder="streamer_login" />
        </label>
        <AuctionSelector auctions={auctions} selectedId={selectedAuction} onSelect={setSelectedAuction} />
      </div>

      {USE_MOCKS ? (
        <article className="card mock-banner">
          <b>Mock mode:</b> UI работает без backend-подключения (данные локальные).
        </article>
      ) : null}

      <ServerStatus />

      <article className="card">
        <h2>{currentAuction?.title ?? "Аукцион не выбран"}</h2>
        <p>
          Статус: <b>{context.data?.status ?? currentAuction?.status ?? "—"}</b>
          {context.data?.seconds_to_end !== null && context.data?.seconds_to_end !== undefined
            ? ` · ${context.data.seconds_to_end} сек до окончания`
            : ""}
        </p>
        <EffectsBadges effects={effects.data} />
      </article>

      <article className="card">
        <h3>Лоты</h3>
        <ul>
          {positions.data?.map((position) => (
            <li key={position.id}>
              {position.name} <strong>{position.total_points}</strong>
            </li>
          )) || <li>Нет данных</li>}
        </ul>
      </article>

      <article className="card">
        <h3>Последние действия</h3>
        <ul>
          {activity.data?.map((item) => (
            <li key={item.id}>
              [{item.event_type}] {item.actor_login}
            </li>
          )) || <li>Пока пусто</li>}
        </ul>
      </article>

      {!compact && context.data?.stream_embed_url ? (
        <article className="card">
          <h3>Стрим</h3>
          <iframe src={context.data.stream_embed_url} title="Twitch stream" allowFullScreen />
        </article>
      ) : null}
    </section>
  );
}

export function ViewerPage() {
  return <AuctionWorkspace />;
}

export function DashboardPage() {
  return <AuctionWorkspace />;
}

export function OverlayPage() {
  return <AuctionWorkspace compact />;
}
