import type { Auction } from "../types";

interface Props {
  auctions: Auction[];
  selectedId?: number;
  onSelect: (id: number) => void;
}

export function AuctionSelector({ auctions, selectedId, onSelect }: Props) {
  return (
    <label className="field">
      Аукцион
      <select
        value={selectedId ?? ""}
        onChange={(event) => onSelect(Number(event.target.value))}
      >
        <option value="" disabled>
          Выберите активный аукцион
        </option>
        {auctions.map((auction) => (
          <option key={auction.id} value={auction.id}>
            {auction.title} · {auction.channel_login} · {auction.status}
          </option>
        ))}
      </select>
    </label>
  );
}
