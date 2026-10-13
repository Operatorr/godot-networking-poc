import type { MapBundle } from "./model";

export type Snapshot = { maps: MapBundle[]; syncedAt: number };

const DB_NAME = "omega-realm-wayfinder";
const STORE = "snapshots";
const KEY = "maps";

function open(): Promise<IDBDatabase> {
	return new Promise((resolve, reject) => {
		const request = indexedDB.open(DB_NAME, 1);
		request.onupgradeneeded = () => {
			request.result.createObjectStore(STORE);
		};
		request.onsuccess = () => resolve(request.result);
		request.onerror = () => reject(request.error);
	});
}

export async function loadSnapshot(): Promise<Snapshot | null> {
	const db = await open();
	try {
		return await new Promise((resolve, reject) => {
			const request = db
				.transaction(STORE, "readonly")
				.objectStore(STORE)
				.get(KEY);
			request.onsuccess = () => resolve((request.result as Snapshot) ?? null);
			request.onerror = () => reject(request.error);
		});
	} finally {
		db.close();
	}
}

export async function saveSnapshot(snapshot: Snapshot): Promise<void> {
	const db = await open();
	try {
		await new Promise<void>((resolve, reject) => {
			const tx = db.transaction(STORE, "readwrite");
			tx.objectStore(STORE).put(snapshot, KEY);
			tx.oncomplete = () => resolve();
			tx.onerror = () => reject(tx.error);
			tx.onabort = () => reject(tx.error);
		});
	} finally {
		db.close();
	}
}
