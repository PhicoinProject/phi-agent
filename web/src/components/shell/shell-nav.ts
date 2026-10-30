// Shell URLs: a room opens /chat?room=<id>.

export function roomHref(roomId: string): string {
  return `/chat?room=${encodeURIComponent(roomId)}`;
}
