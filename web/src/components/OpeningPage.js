"use client";

import { motion } from "framer-motion";

export default function OpeningPage({ onEnterClick }) {
  return (
    <div className="min-h-screen bg-gradient-to-b from-indigo-950 via-blue-900 to-sky-700 flex items-center justify-center px-4">
      <motion.div
        className="text-center max-w-2xl"
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: "easeOut" }}
      >
        <motion.div
          className="text-8xl mb-6"
          animate={{ scale: [1, 1.06, 1] }}
          transition={{ duration: 2.4, repeat: Infinity, ease: "easeInOut" }}
          aria-hidden
        >
          ⚡
        </motion.div>
        <h1 className="text-6xl font-bold text-white mb-4">Tempo</h1>
        <h2 className="text-2xl text-amber-200 mb-8 font-semibold">Forecast. Decide. Audit.</h2>
        <p className="text-xl text-gray-100 mb-12 leading-relaxed">
          A battery trader for the GB electricity market that decides when to charge, sell or hold, then proves,
          half-hour by half-hour, whether it picked the right moment.
        </p>
        <button
          onClick={onEnterClick}
          className="px-8 py-4 bg-white text-blue-900 font-bold text-lg rounded-lg hover:bg-gray-100 cursor-pointer transition-colors duration-200 shadow-lg"
        >
          Enter App
        </button>
      </motion.div>
    </div>
  );
}
