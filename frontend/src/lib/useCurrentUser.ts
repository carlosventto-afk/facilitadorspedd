"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { UserProfile } from "@/types";

export function useCurrentUser(): { user: UserProfile | null; loading: boolean } {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<UserProfile>("/auth/me")
      .then((r) => setUser(r.data))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  return { user, loading };
}
