// Smoke tests: the built page, the real chat backend, and the fake gateway behind it.
// The fake answers instantly unless the message asks it to be slow, so every wait below is
// for something to appear, never for an amount of time.

import { expect, test, type Page } from "@playwright/test";

async function send(page: Page, text: string) {
  await page.getByRole("textbox", { name: "Message" }).fill(text);
  await page.getByRole("button", { name: "Send" }).click();
}

test("a turn goes through the gateway and comes back with its numbers", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Gateway chat" })).toBeVisible();
  await expect(page.getByText(/^Gateway at http:\/\/127\.0\.0\.1:8199/)).toBeVisible();
  await expect(page.getByRole("radio")).toHaveCount(3);

  await page.getByRole("radio", { name: /acme/ }).check();
  const budget = page.getByText(/tokens left$/);
  const before = await budget.textContent();
  await send(page, "Hello");

  const reply = page.getByRole("article", { name: "Reply" }).last();
  await expect(reply).toContainText("Fake reply from premium.");
  await expect(reply.locator(".badge.model")).toHaveText("premium");
  await expect(reply.getByText("First token")).toBeVisible();
  // The budget is read back from the gateway after the turn.
  await expect(budget).not.toHaveText(before ?? "");

  // Same conversation, cheaper model.
  await page.getByRole("combobox", { name: "Model choice" }).selectOption("quality:cheapest");
  await send(page, "Again");
  await expect(page.getByRole("article", { name: "Reply" }).last()).toContainText(
    "Fake reply from economy.",
  );
  expect(errors).toEqual([]);
});

test("the gateway enforces the plan", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("radio", { name: /initech/ }).check();
  await page.getByRole("combobox", { name: "Model choice" }).selectOption("model:premium");
  await send(page, "Hi");
  await expect(page.getByRole("alert")).toContainText("Not in this tenant's plan (HTTP 403)");
});

test("stop cuts a reply off", async ({ page }) => {
  await page.goto("/");
  await send(page, "[[slow]]");
  const reply = page.getByRole("article", { name: "Reply" }).last();
  await expect(reply).toContainText("tokens so far");
  await page.getByRole("button", { name: "Stop" }).click();
  await expect(reply).toContainText("Stopped.");
  await expect(page.getByRole("button", { name: "Send" })).toBeVisible();
});

test("a model server that is down is reported", async ({ page }) => {
  await page.goto("/");
  await send(page, "[[backend-down]]");
  await expect(page.getByRole("alert")).toContainText("Model server not reachable (HTTP 502)");
});
