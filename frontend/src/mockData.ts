import type { ActivityItem, Auction, Effects, Position, UiContext } from "./types";

export const MOCK_AUCTIONS: Auction[] = [
  {
    id: 101,
    channel_login: "demo_streamer",
    title: "Выбираем игру на вечер",
    status: "active",
    created_at: "2026-02-01T18:00:00Z",
    started_at: "2026-02-01T18:10:00Z",
    ended_at: null,
  },
  {
    id: 102,
    channel_login: "demo_streamer",
    title: "Фильм выходного дня",
    status: "locked",
    created_at: "2026-02-02T18:00:00Z",
    started_at: "2026-02-02T18:05:00Z",
    ended_at: null,
  },
];

export const MOCK_POSITIONS: Record<number, Position[]> = {
  101: [
    { id: 1, auction_id: 101, name: "Hades II", total_points: 164000 },
    { id: 2, auction_id: 101, name: "Baldur's Gate 3", total_points: 143500 },
    { id: 3, auction_id: 101, name: "Terraria", total_points: 98500 },
  ],
  102: [
    { id: 4, auction_id: 102, name: "Dune: Part Two", total_points: 251000 },
    { id: 5, auction_id: 102, name: "Interstellar", total_points: 238000 },
  ],
};

export const MOCK_ACTIVITY: Record<number, ActivityItem[]> = {
  101: [
    {
      id: 1001,
      auction_id: 101,
      event_type: "contribution_created",
      actor_login: "viewer_one",
      payload: { position: "Hades II", amount: 10000 },
      created_at: "2026-02-01T18:31:10Z",
    },
    {
      id: 1002,
      auction_id: 101,
      event_type: "contribution_created",
      actor_login: "viewer_two",
      payload: { position: "Baldur's Gate 3", amount: 50000 },
      created_at: "2026-02-01T18:30:02Z",
    },
  ],
  102: [
    {
      id: 1003,
      auction_id: 102,
      event_type: "auction_locked",
      actor_login: "demo_streamer",
      payload: {},
      created_at: "2026-02-02T18:55:00Z",
    },
  ],
};

export const MOCK_CONTEXT: Record<number, UiContext> = {
  101: {
    auction_id: 101,
    status: "active",
    stream_embed_url: "https://player.twitch.tv/?channel=demo_streamer&parent=localhost",
    seconds_to_end: 840,
  },
  102: {
    auction_id: 102,
    status: "locked",
    stream_embed_url: "https://player.twitch.tv/?channel=demo_streamer&parent=localhost",
    seconds_to_end: null,
  },
};

export const MOCK_EFFECTS: Record<number, Effects> = {
  101: {
    has_new_activity: true,
    leader_changed: true,
    has_large_contribution: true,
    ending_soon: true,
  },
  102: {
    has_new_activity: false,
    leader_changed: false,
    has_large_contribution: false,
    ending_soon: false,
  },
};
