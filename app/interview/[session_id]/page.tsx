"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";

export default function LegacyInterviewRoute() {
  const { session_id } = useParams<{ session_id: string }>();
  const router = useRouter();

  useEffect(() => {
    if (!session_id || session_id === "undefined") {
      router.replace("/");
      return;
    }
    router.replace(`/interview-room/${encodeURIComponent(session_id)}`);
  }, [router, session_id]);

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        background: "#020707",
        color: "#f5f7f7",
        fontFamily: "Inter, system-ui, sans-serif",
      }}
    >
      <p style={{ opacity: 0.72 }}>Opening interview room...</p>
    </main>
  );
}
