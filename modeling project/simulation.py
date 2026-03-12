import tkinter as tk
from tkinter import ttk, messagebox

class FuelSimGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Vehicle Fuel Consumption Simulation")
        self.root.resizable(False, False)

        # -----------------------------
        # DEFAULT PARAMETERS
        # -----------------------------
        self.default_initial_fuel = 40.0         # liters
        self.default_consumption_rate = 0.15     # liters per minute
        self.default_warning_threshold = 5.0     # liters
        self.default_speed_kmh = 80.0            # km/h

        # Simulation timing
        self.time_step_min = 1     # simulation step (minutes)
        self.tick_ms = 200         # real-time update interval (ms)

        # -----------------------------
        # STATE
        # -----------------------------
        self.running = False
        self.after_id = None
        self.low_warn_shown = False

        # Active parameters (loaded from UI)
        self.initial_fuel = self.default_initial_fuel
        self.consumption_rate = self.default_consumption_rate
        self.warning_threshold = self.default_warning_threshold
        self.speed_kmh = self.default_speed_kmh

        self.reset_state()

        # -----------------------------
        # UI
        # -----------------------------
        header = tk.Label(root, text="Vehicle Fuel Consumption (Highway Trip)", font=("Arial", 14, "bold"))
        header.grid(row=0, column=0, columnspan=4, pady=(12, 6))

        # ---- Editable Inputs Frame
        inp = tk.LabelFrame(root, text="Inputs (Editable)", padx=10, pady=8)
        inp.grid(row=1, column=0, columnspan=4, padx=10, pady=(0, 10), sticky="ew")

        tk.Label(inp, text="Initial Fuel (L):").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.initial_fuel_var = tk.StringVar(value=str(self.default_initial_fuel))
        self.initial_fuel_entry = ttk.Entry(inp, textvariable=self.initial_fuel_var, width=12)
        self.initial_fuel_entry.grid(row=0, column=1, padx=6, pady=4)

        tk.Label(inp, text="Speed (km/h):").grid(row=0, column=2, sticky="w", padx=6, pady=4)
        self.speed_var = tk.StringVar(value=str(self.default_speed_kmh))
        self.speed_entry = ttk.Entry(inp, textvariable=self.speed_var, width=12)
        self.speed_entry.grid(row=0, column=3, padx=6, pady=4)

        tk.Label(inp, text="Burn Rate (L/min):").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.rate_var = tk.StringVar(value=str(self.default_consumption_rate))
        self.rate_entry = ttk.Entry(inp, textvariable=self.rate_var, width=12)
        self.rate_entry.grid(row=1, column=1, padx=6, pady=4)

        tk.Label(inp, text="Warning (L):").grid(row=1, column=2, sticky="w", padx=6, pady=4)
        self.warn_var = tk.StringVar(value=str(self.default_warning_threshold))
        self.warn_entry = ttk.Entry(inp, textvariable=self.warn_var, width=12)
        self.warn_entry.grid(row=1, column=3, padx=6, pady=4)

        self.apply_btn = ttk.Button(inp, text="Apply Inputs", command=self.apply_inputs)
        self.apply_btn.grid(row=2, column=0, columnspan=4, pady=(6, 0))

        # ---- Fuel Gauge
        tk.Label(root, text="Fuel Level:", font=("Arial", 10, "bold")).grid(row=2, column=0, sticky="w", padx=10, pady=4)
        self.fuel_var = tk.StringVar(value=f"{self.fuel:.2f} L")
        tk.Label(root, textvariable=self.fuel_var, font=("Arial", 10)).grid(row=2, column=3, sticky="e", padx=10, pady=4)

        self.fuel_bar = ttk.Progressbar(root, orient="horizontal", length=420, mode="determinate")
        self.fuel_bar.grid(row=3, column=0, columnspan=4, padx=10, pady=(0, 10))
        self.fuel_bar["maximum"] = self.initial_fuel
        self.fuel_bar["value"] = self.fuel

        # ---- Info Row
        info = tk.Frame(root)
        info.grid(row=4, column=0, columnspan=4, padx=10, pady=(0, 8), sticky="ew")

        self.time_var = tk.StringVar(value=f"Time: {self.time_min} min")
        self.dist_var = tk.StringVar(value=f"Distance: {self.distance_km:.2f} km")
        self.status_var = tk.StringVar(value="Status: OK")

        tk.Label(info, textvariable=self.time_var, width=16, anchor="w").grid(row=0, column=0, padx=6)
        tk.Label(info, textvariable=self.dist_var, width=22, anchor="w").grid(row=0, column=1, padx=6)
        self.status_label = tk.Label(info, textvariable=self.status_var, width=14, anchor="w", font=("Arial", 10, "bold"))
        self.status_label.grid(row=0, column=2, padx=6)

        # ---- Controls
        controls = tk.Frame(root)
        controls.grid(row=5, column=0, columnspan=4, pady=(4, 12))

        self.start_btn = ttk.Button(controls, text="Start", command=self.start)
        self.pause_btn = ttk.Button(controls, text="Pause", command=self.pause, state="disabled")
        self.reset_btn = ttk.Button(controls, text="Reset", command=self.reset)

        self.start_btn.grid(row=0, column=0, padx=6)
        self.pause_btn.grid(row=0, column=1, padx=6)
        self.reset_btn.grid(row=0, column=2, padx=6)

        # Footer
        self.footer_var = tk.StringVar()
        self.footer = tk.Label(root, textvariable=self.footer_var, font=("Arial", 9), fg="gray")
        self.footer.grid(row=6, column=0, columnspan=4, pady=(0, 10))

        self.update_footer()
        self.update_ui()

    # -----------------------------
    # VALIDATION + APPLY INPUTS
    # -----------------------------
    def apply_inputs(self):
        if self.running:
            messagebox.showinfo("Pause Needed", "Please pause the simulation before applying new inputs.")
            return

        try:
            f0 = float(self.initial_fuel_var.get())
            v = float(self.speed_var.get())
            rc = float(self.rate_var.get())
            fw = float(self.warn_var.get())

            if f0 <= 0 or v <= 0 or rc <= 0:
                raise ValueError("Initial fuel, speed, and burn rate must be > 0.")
            if fw < 0:
                raise ValueError("Warning threshold must be ≥ 0.")
            if fw > f0:
                raise ValueError("Warning threshold must be ≤ initial fuel.")
        except Exception as e:
            messagebox.showerror("Invalid Input", f"Please check your values.\n\nError: {e}")
            return

        # Apply
        self.initial_fuel = f0
        self.speed_kmh = v
        self.consumption_rate = rc
        self.warning_threshold = fw

        # Reset sim state with new parameters
        self.reset_state()
        self.fuel_bar["maximum"] = self.initial_fuel
        self.update_footer()
        self.update_ui()

        messagebox.showinfo("Applied", "Inputs applied successfully!")

    def update_footer(self):
        self.footer_var.set(
            f"Burn rate: {self.consumption_rate} L/min | Warning: ≤ {self.warning_threshold} L | Speed: {self.speed_kmh} km/h"
        )

    # -----------------------------
    # SIM STATE + UI
    # -----------------------------
    def reset_state(self):
        self.fuel = self.initial_fuel
        self.time_min = 0
        self.distance_km = 0.0
        self.low_warn_shown = False

    def update_ui(self):
        self.fuel_var.set(f"{self.fuel:.2f} L")
        self.time_var.set(f"Time: {self.time_min} min")
        self.dist_var.set(f"Distance: {self.distance_km:.2f} km")
        self.fuel_bar["value"] = self.fuel

        if self.fuel <= 0:
            self.status_var.set("Status: EMPTY")
            self.status_label.config(fg="red")
        elif self.fuel <= self.warning_threshold:
            self.status_var.set("Status: LOW")
            self.status_label.config(fg="orange")
        else:
            self.status_var.set("Status: OK")
            self.status_label.config(fg="green")

    # -----------------------------
    # SIM LOOP
    # -----------------------------
    def step(self):
        if not self.running:
            return

        # Low fuel warning popup (once)
        if (self.fuel <= self.warning_threshold) and (self.fuel > 0) and (not self.low_warn_shown):
            self.low_warn_shown = True
            messagebox.showwarning(
                "Low Fuel Warning",
                f"Fuel is low (≤ {self.warning_threshold} L).\nCurrent fuel: {self.fuel:.2f} L"
            )

        # Consume fuel
        self.fuel -= (self.consumption_rate * self.time_step_min)
        if self.fuel < 0:
            self.fuel = 0.0

        # Update time + distance
        self.time_min += self.time_step_min
        self.distance_km = (self.speed_kmh / 60.0) * self.time_min

        self.update_ui()

        # Stop when empty
        if self.fuel <= 0:
            self.running = False
            self.start_btn.config(state="normal")
            self.pause_btn.config(state="disabled")
            messagebox.showinfo(
                "Tank Empty",
                f"The fuel tank is empty.\nTime: {self.time_min} min\nDistance: {self.distance_km:.2f} km"
            )
            return

        self.after_id = self.root.after(self.tick_ms, self.step)

    def start(self):
        if self.running:
            return
        self.running = True
        self.start_btn.config(state="disabled")
        self.pause_btn.config(state="normal")
        self.step()

    def pause(self):
        self.running = False
        self.start_btn.config(state="normal")
        self.pause_btn.config(state="disabled")
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None

    def reset(self):
        self.pause()
        self.reset_state()
        self.update_ui()

# -----------------------------
# RUN APP
# -----------------------------
if __name__ == "__main__":
    root = tk.Tk()
    app = FuelSimGUI(root)
    root.mainloop()