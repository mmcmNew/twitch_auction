import type { ActivityItem, Auction, Effects, Position, UiContext } from "./types";
import { MOCK_ACTIVITY, MOCK_AUCTIONS, MOCK_CONTEXT, MOCK_EFFECTS, MOCK_POSITIONS } from "./mockData";

const API_URL = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";
export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === "1";

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`);
  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function simulateLatency<T>(value: T): Promise<T> {
  return new Promise((resolve) => {
    setTimeout(() => resolve(value), 150);
  });
}

export const api = {
  listAuctions: (channelLogin?: string) => {
    if (USE_MOCKS) {
      const data = channelLogin
        ? MOCK_AUCTIONS.filter((auction) => auction.channel_login === channelLogin)
        : MOCK_AUCTIONS;
      return simulateLatency(data);
    }

    return request<Auction[]>(
      `/auctions?limit=20${channelLogin ? `&channel_login=${channelLogin}` : ""}`,
    );
  },
  getPositions: (auctionId: number) => {
    if (USE_MOCKS) {
      return simulateLatency(MOCK_POSITIONS[auctionId] ?? []);
    }
    return request<Position[]>(`/auctions/${auctionId}/positions`);
  },
  getActivity: (auctionId: number) => {
    if (USE_MOCKS) {
      return simulateLatency(MOCK_ACTIVITY[auctionId] ?? []);
    }
    return request<ActivityItem[]>(`/auctions/${auctionId}/activity?limit=20`);
  },
  getUiContext: (auctionId: number) => {
    if (USE_MOCKS) {
      const fallback: UiContext = {
        auction_id: auctionId,
        status: "draft",
        stream_embed_url: "https://player.twitch.tv/?channel=demo_streamer&parent=localhost",
        seconds_to_end: null,
      };
      return simulateLatency(MOCK_CONTEXT[auctionId] ?? fallback);
    }
    return request<UiContext>(`/auctions/${auctionId}/ui-context`);
  },
  getEffects: (auctionId: number) => {
    if (USE_MOCKS) {
      return simulateLatency(
        MOCK_EFFECTS[auctionId] ?? {
          has_new_activity: false,
          leader_changed: false,
          has_large_contribution: false,
          ending_soon: false,
        },
      );
    }
    return request<Effects>(`/auctions/${auctionId}/effects`);
  },
};

export const eventsUrl = (auctionId: number) => `${API_URL}/auctions/${auctionId}/events`;

export async function checkServerHealth(): Promise<unknown> {
  if (USE_MOCKS) {
    return { status: "ok", mode: "mock" };
  }

  return request<unknown>("/health");
}
