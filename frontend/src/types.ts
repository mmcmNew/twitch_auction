export type AuctionStatus =
  | "draft"
  | "active"
  | "locked"
  | "roulette_running"
  | "closed";

export interface Auction {
  id: number;
  channel_login: string;
  title: string;
  status: AuctionStatus;
  created_at: string;
  started_at?: string | null;
  ended_at?: string | null;
}

export interface Position {
  id: number;
  auction_id: number;
  name: string;
  total_points: number;
}

export interface ActivityItem {
  id: number;
  auction_id: number;
  event_type: string;
  actor_login: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface UiContext {
  auction_id: number;
  status: AuctionStatus;
  stream_embed_url: string;
  seconds_to_end: number | null;
}

export interface Effects {
  has_new_activity: boolean;
  leader_changed: boolean;
  has_large_contribution: boolean;
  ending_soon: boolean;
}
