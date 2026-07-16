import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import security from "eslint-plugin-security";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended, security.configs.recommended],
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // Hook/provider files intentionally co-export a hook + component (useAccount,
      // useAuth); splitting them just for Fast Refresh isn't worth the churn.
      "react-refresh/only-export-components": "off",
      // Flags every dynamic property/array access (obj[key]) regardless of whether
      // the key is attacker-controlled — in a typed codebase this is mostly noise.
      // The rest of eslint-plugin-security's recommended rules stay on.
      "security/detect-object-injection": "off",
    },
  },
);
