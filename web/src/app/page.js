"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import OpeningPage from "@/components/OpeningPage";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    router.prefetch("/dashboard");
  }, [router]);

  return <OpeningPage onEnterClick={() => router.push("/dashboard")} />;
}
