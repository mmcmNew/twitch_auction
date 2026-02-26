import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { USE_MOCKS, api, eventsUrl } from "./api";

export const useAuctions = (channel?: string) =>
  useQuery({
    queryKey: ["auctions", channel],
    queryFn: () => api.listAuctions(channel),
    refetchInterval: 15000,
  });

export const useAuctionData = (auctionId?: number) => {
  const enabled = Boolean(auctionId);
  return {
    positions: useQuery({
      queryKey: ["positions", auctionId],
      queryFn: () => api.getPositions(auctionId!),
      enabled,
    }),
    activity: useQuery({
      queryKey: ["activity", auctionId],
      queryFn: () => api.getActivity(auctionId!),
      enabled,
    }),
    context: useQuery({
      queryKey: ["context", auctionId],
      queryFn: () => api.getUiContext(auctionId!),
      enabled,
    }),
    effects: useQuery({
      queryKey: ["effects", auctionId],
      queryFn: () => api.getEffects(auctionId!),
      enabled,
    }),
  };
};

export function useAuctionEvents(auctionId?: number) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!auctionId || USE_MOCKS) {
      return;
    }

    const source = new EventSource(eventsUrl(auctionId));
    source.onmessage = () => {
      queryClient.invalidateQueries({ queryKey: ["positions", auctionId] });
      queryClient.invalidateQueries({ queryKey: ["activity", auctionId] });
      queryClient.invalidateQueries({ queryKey: ["context", auctionId] });
      queryClient.invalidateQueries({ queryKey: ["effects", auctionId] });
    };

    source.onerror = () => {
      source.close();
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["positions", auctionId] });
      }, 3000);
    };

    return () => source.close();
  }, [auctionId, queryClient]);
}
