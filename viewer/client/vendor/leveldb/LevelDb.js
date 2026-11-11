// Copyright (c) Microsoft Corporation.
// Licensed under the MIT License.
/* eslint-disable no-case-declarations */
import * as pako from "../pako.js";
import DataUtilities from "./DataUtilities.js";
import LevelDbIndex from "./LevelDbIndex.js";
import LevelKeyValue from "./LevelKeyValue.js";
import Utilities from "./Utilities.js";
import Varint from "./Varint.js";
export default class LevelDb {
    logger;
    ldbFiles;
    logFiles;
    manifestFiles;
    keys = new Map();
    isInErrorState;
    errorMessages;
    comparator;
    logNumber;
    previousLogNumber;
    nextFileNumber;
    lastSequence;
    compactPointerLevels;
    compactPointerStrings;
    deletedFileLevel;
    deletedFileNumber;
    newFileLevel;
    newFileNumber;
    newFileSize;
    newFileSmallest;
    newFileLargest;
    context;
    /** Index for lazy loading - tracks file metadata without loading content */
    #index;
    /** Whether lazy loading mode is enabled */
    #isLazyMode = false;
    /** Maximum keys to keep in memory during lazy mode */
    #maxKeysInMemory = 50000;
    /** LRU tracking for key eviction in lazy mode */
    #keyAccessOrder = [];
    /** Set of keys that have been loaded but may be evicted */
    #loadedKeys = new Set();
    /** Whether initial metadata has been loaded */
    #isInitialized = false;
    static #yieldInterval = 10;
    /** Get whether lazy loading mode is enabled */
    get isLazyMode() {
        return this.#isLazyMode;
    }
    /** Get the file index for lazy loading */
    get index() {
        return this.#index;
    }
    #tryInflate(content, raw) {
        try {
            return pako.inflate(content, { raw: raw });
        }
        catch {
            return undefined;
        }
    }
    /** Get the number of keys currently in memory */
    get keysInMemoryCount() {
        return this.keys.size;
    }
    /**
     * @param logger If provided, logs will go through here. If not present, it will default to console logs. To disable all logging, pass an empty object `{}`.
     */
    constructor(ldbFileArr, logFileArr, manifestFilesArr, context, logger) {
        this.ldbFiles = ldbFileArr;
        this.logFiles = logFileArr;
        this.manifestFiles = manifestFilesArr;
        this.context = context;
        this.logger = logger ?? {
            log: message => console.log(`[LevelDb] ${message}`),
            verbose: message => console.debug(`[LevelDb] ${message}`),
            error: message => console.error(`[LevelDb] ${message}`),
            assert: console.assert
        };
    }
    #pushError(message, contextIn) {
        this.isInErrorState = true;
        if (this.errorMessages === undefined) {
            this.errorMessages = [];
        }
        let contextOut;
        if (contextIn) {
            contextOut = this.context ? this.context + "-" + contextIn : contextIn;
        }
        else {
            contextOut = this.context;
        }
        this.logger.error?.(message + (contextOut ? " " + contextOut : ""));
        this.errorMessages.push({
            message: message,
            context: contextOut
        });
        return message;
    }
    async init(options) {
        this.keys = new Map();
        this.isInErrorState = false;
        this.errorMessages = undefined;
        const unloadAfterParse = options?.unloadFilesAfterParse ?? false;
        for (let i = 0; i < this.manifestFiles.length; i++) {
            const content = this.manifestFiles[i].content;
            if (content instanceof Uint8Array && content.length > 0) {
                this.parseManifestContent(content, this.manifestFiles[i].storageRelativePath);
                this.logger.log?.("Loaded map manifest file '" + this.manifestFiles[i].fullPath + "'.");
            }
            // Unload file content to free memory after parsing
            if (unloadAfterParse) {
                this.manifestFiles[i].unload();
            }
        }
        const ldbFileInfos = [];
        for (let i = 0; i < this.ldbFiles.length; i++) {
            const file = this.ldbFiles[i];
            try {
                const index = parseInt(file.name);
                if (!this.deletedFileNumber || !this.deletedFileNumber.includes(index)) {
                    let level = 0;
                    if (this.newFileLevel && this.newFileNumber) {
                        this.logger.assert?.(this.newFileLevel.length === this.newFileNumber.length);
                        if (this.newFileLevel.length === this.newFileNumber.length) {
                            for (let j = 0; j < this.newFileNumber.length; j++) {
                                if (this.newFileNumber[j] === index) {
                                    level = this.newFileLevel[j];
                                }
                            }
                        }
                    }
                    ldbFileInfos.push({
                        index: index,
                        file: file,
                        isDeleted: false,
                        level: level
                    });
                }
            }
            catch (e) {
                this.#pushError(`Error including LDB file: ${file.fullPath} Error: ${e}`);
            }
        }
        const ldbFileInfoSorted = ldbFileInfos.sort((fileA, fileB) => {
            if (fileA.level === fileB.level) {
                return fileA.index - fileB.index;
            }
            return fileB.level - fileA.level;
        });
        for (let i = 0; i < ldbFileInfoSorted.length; i++) {
            const ldbFile = ldbFileInfoSorted[i].file;
            const content = ldbFile.content;
            if (content instanceof Uint8Array && content.length > 0) {
                const kp = this.parseLdbContent(content, ldbFile.storageRelativePath);
                this.logger.log?.("Loaded map record file '" + ldbFile.fullPath + "'. Records: " + kp);
            }
            // Unload file content to free memory after parsing
            if (unloadAfterParse) {
                ldbFile.unload();
            }
            // Periodically yield to the event loop to allow garbage collection
            // This helps prevent out-of-memory errors when loading large worlds
            if (i % LevelDb.#yieldInterval === 0 && i > 0) {
                await new Promise(resolve => setTimeout(resolve, 0));
            }
        }
        const logFilesSorted = this.logFiles.sort((fileA, fileB) => {
            return fileA.name.localeCompare(fileB.name);
        });
        for (let i = 0; i < logFilesSorted.length; i++) {
            const content = logFilesSorted[i].content;
            if (content instanceof Uint8Array && content.length > 0) {
                const kp = this.parseLogContent(content, logFilesSorted[i].storageRelativePath);
                this.logger.log?.("Loaded map latest-updates file '" + logFilesSorted[i].fullPath + "'. Records: " + kp);
            }
            // Unload file content to free memory after parsing
            if (unloadAfterParse) {
                logFilesSorted[i].unload();
            }
            // Periodically yield to allow garbage collection
            if (i % LevelDb.#yieldInterval === 0 && i > 0) {
                await new Promise(resolve => setTimeout(resolve, 0));
            }
        }
    }
    /**
     * Initialize in lazy loading mode - only loads manifest metadata.
     * Files are loaded on-demand when keys are requested.
     *
     * This dramatically reduces initial memory usage for large worlds.
     * Call loadAllFiles() to fully load everything, or use getKey() for on-demand loading.
     */
    async initLazy(options) {
        this.keys = new Map();
        this.isInErrorState = false;
        this.errorMessages = undefined;
        this.#isLazyMode = true;
        this.#maxKeysInMemory = options?.maxKeysInMemory ?? 50000;
        this.#keyAccessOrder = [];
        this.#loadedKeys = new Set();
        // Load manifest to get file metadata
        for (let i = 0; i < this.manifestFiles.length; i++) {
            const content = this.manifestFiles[i].content;
            if (content instanceof Uint8Array && content.length > 0) {
                this.parseManifestContent(content, this.manifestFiles[i].storageRelativePath);
            }
            // Unload manifest content - we've extracted the metadata
            this.manifestFiles[i].unload();
        }
        // Build the index from manifest metadata
        this.#index = new LevelDbIndex();
        this.#index.initFromManifest(this.ldbFiles, this.logFiles, this.newFileLevel, this.newFileNumber, this.newFileSmallest, this.newFileLargest, this.deletedFileNumber);
        this.#isInitialized = true;
    }
    /**
     * Load all files in lazy mode. This is useful after initLazy() when you want
     * to fully populate all keys (e.g., for world enumeration).
     *
     * @param options Options for loading
     * @returns The number of keys loaded
     */
    async loadAllFiles(options) {
        if (!this.#isInitialized || !this.#index) {
            throw new Error("LevelDb must be initialized before loading files");
        }
        const unloadAfterParse = options?.unloadFilesAfterParse ?? true;
        const yieldInterval = 10;
        let filesProcessed = 0;
        const totalFiles = this.#index.totalFiles;
        // Load LDB files in order (sorted by level for correct supercession)
        for (let i = 0; i < this.#index.ldbFileIndexes.length; i++) {
            const fileIdx = this.#index.ldbFileIndexes[i];
            const file = fileIdx.fileInfo.file;
            const content = file.content;
            if (content instanceof Uint8Array && content.length > 0) {
                this.parseLdbContent(content, file.storageRelativePath);
            }
            fileIdx.isLoaded = true;
            if (unloadAfterParse) {
                file.unload();
            }
            filesProcessed++;
            if (options?.progressCallback && filesProcessed % 5 === 0) {
                options.progressCallback("Summarizing all world files", filesProcessed, totalFiles);
            }
            // Yield periodically for GC
            if (i % yieldInterval === 0 && i > 0) {
                await new Promise(resolve => setTimeout(resolve, 0));
            }
        }
        // Load LOG files in order (sorted by name for correct supercession)
        for (let i = 0; i < this.#index.logFileIndexes.length; i++) {
            const fileIdx = this.#index.logFileIndexes[i];
            const file = fileIdx.file;
            const content = file.content;
            if (content instanceof Uint8Array && content.length > 0) {
                this.parseLogContent(content, file.storageRelativePath);
            }
            fileIdx.isLoaded = true;
            if (unloadAfterParse) {
                file.unload();
            }
            filesProcessed++;
            if (options?.progressCallback) {
                options.progressCallback("Loading LOG files", filesProcessed, totalFiles);
            }
            // Yield periodically for GC
            if (i % yieldInterval === 0 && i > 0) {
                await new Promise(resolve => setTimeout(resolve, 0));
            }
        }
        return this.keys.size;
    }
    /**
     * Load a specific file's keys into memory.
     * Used for on-demand loading in lazy mode.
     */
    async loadFile(fileIndex) {
        const isLogFile = "name" in fileIndex; // ILevelDbLogIndex has 'name', ILevelDbFileIndex doesn't
        const file = isLogFile ? fileIndex.file : fileIndex.fileInfo.file;
        const content = file.content;
        let keysParsed = 0;
        if (content instanceof Uint8Array && content.length > 0) {
            if (isLogFile) {
                keysParsed = this.parseLogContent(content, file.storageRelativePath) || 0;
            }
            else {
                keysParsed = this.parseLdbContent(content, file.storageRelativePath) || 0;
            }
        }
        fileIndex.isLoaded = true;
        file.unload(); // Always unload in lazy mode
        return keysParsed;
    }
    // Track the last parsed size for each log file to enable incremental parsing
    #logFileParsedSizes = new Map();
    /**
     * Parse a new or modified LDB/LOG file and return the chunk coordinates affected.
     * This is used for incremental updates when the file system detects new files.
     *
     * @param file The LDB or LOG file to parse
     * @returns Array of unique chunk coordinates affected by keys in this file
     */
    async parseIncrementalFile(file) {
        const affectedChunks = [];
        const seenChunks = new Set();
        // For incremental updates, always force reload the file content
        // The file may have been updated (especially .log files which are append-only)
        if (file.isContentLoaded) {
            file.unload();
        }
        const content = file.content;
        if (!(content instanceof Uint8Array) || content.length === 0) {
            return affectedChunks;
        }
        const isLogFile = file.name.toLowerCase().endsWith(".log");
        const filePath = file.storageRelativePath || file.fullPath;
        // For log files, check if the file has grown since last parse
        const previousSize = this.#logFileParsedSizes.get(filePath) || 0;
        const currentSize = content.length;
        if (isLogFile && currentSize <= previousSize) {
            // File hasn't grown, no new data
            file.unload();
            return affectedChunks;
        }
        // Track keys before parsing
        const keysBefore = new Map();
        for (const [key, val] of this.keys) {
            keysBefore.set(key, val);
        }
        // Parse the file
        if (isLogFile) {
            // For log files, parse and extract chunks from ALL keys in the file that are chunk-related
            // This is because log files are append-only and we need to catch any chunk updates
            this.parseLogContent(content, file.storageRelativePath);
            this.#logFileParsedSizes.set(filePath, currentSize);
            // For log files that have grown, find all keys that now have different values
            // (parseLogContent creates new LevelKeyValue objects, so any updated key will have a different reference)
            for (const [keyname, keyValue] of this.keys) {
                if (!keyValue || typeof keyValue === "boolean") {
                    continue;
                }
                const prevValue = keysBefore.get(keyname);
                // Skip if key existed with same object reference (wasn't updated)
                if (prevValue === keyValue) {
                    continue;
                }
                // This is either a new key or an updated key (different object reference)
                // Extract chunk coordinates
                this.#extractChunkFromKey(keyname, seenChunks, affectedChunks);
            }
        }
        else {
            // For LDB files, use the original approach of tracking new/updated keys
            this.parseLdbContent(content, file.storageRelativePath);
            // Find new/updated keys and extract chunk coordinates
            for (const [keyname, keyValue] of this.keys) {
                if (!keyValue) {
                    continue;
                }
                const prevValue = keysBefore.get(keyname);
                if (prevValue === keyValue) {
                    continue;
                } // Same object reference = no change
                this.#extractChunkFromKey(keyname, seenChunks, affectedChunks);
            }
        }
        // Unload file content to free memory
        file.unload();
        // Add file to our tracking arrays if not already present
        if (isLogFile && !this.logFiles.includes(file)) {
            this.logFiles.push(file);
        }
        else if (!isLogFile && !this.ldbFiles.includes(file)) {
            this.ldbFiles.push(file);
        }
        return affectedChunks;
    }
    /**
     * Extract chunk coordinates from a key name if it represents chunk data.
     */
    #extractChunkFromKey(keyname, seenChunks, affectedChunks) {
        // Extract chunk coordinates from key (9-14 byte keys encode chunk data)
        if (keyname.length < 9 || keyname.length > 14) {
            return false;
        }
        // Skip named keys
        if (keyname.startsWith("AutonomousEntities") ||
            keyname.startsWith("schedulerWT") ||
            keyname.startsWith("Overworld") ||
            keyname.startsWith("BiomeData") ||
            keyname.startsWith("digp") ||
            keyname.startsWith("actorprefix") ||
            keyname.startsWith("player") ||
            keyname.startsWith("portals")) {
            return false;
        }
        const hasDimensionParam = keyname.length >= 13;
        const x = DataUtilities.getSignedInteger(keyname.charCodeAt(0), keyname.charCodeAt(1), keyname.charCodeAt(2), keyname.charCodeAt(3), true);
        const z = DataUtilities.getSignedInteger(keyname.charCodeAt(4), keyname.charCodeAt(5), keyname.charCodeAt(6), keyname.charCodeAt(7), true);
        let dim = 0;
        if (hasDimensionParam) {
            dim = DataUtilities.getSignedInteger(keyname.charCodeAt(8), keyname.charCodeAt(9), keyname.charCodeAt(10), keyname.charCodeAt(11), true);
            if (dim < 0 || dim > 2) {
                return false; // Invalid dimension
            }
        }
        // Track unique chunks
        const chunkKey = `${dim}_${x}_${z}`;
        if (!seenChunks.has(chunkKey)) {
            seenChunks.add(chunkKey);
            affectedChunks.push({
                x,
                z,
                dimension: dim
            });
            return true;
        }
        return false;
    }
    /**
     * Evict old keys to stay under the memory limit.
     * Uses LRU (least recently used) eviction.
     */
    #dropKey(key) {
        const keyValue = this.keys.get(key);
        if (keyValue && typeof keyValue !== "boolean") {
            keyValue.clearAllData();
        }
        this.keys.delete(key);
        this.#loadedKeys.delete(key);
    }
    #markFilesUnloaded() {
        if (!this.#index) {
            return;
        }
        for (const fileIdx of this.#index.ldbFileIndexes) {
            fileIdx.isLoaded = false;
        }
        for (const fileIdx of this.#index.logFileIndexes) {
            fileIdx.isLoaded = false;
        }
    }
    #evictKeysIfNeeded() {
        if (!this.#isLazyMode || this.keys.size <= this.#maxKeysInMemory) {
            return;
        }
        const keep = Math.max(1, Math.floor(this.#maxKeysInMemory * 0.8));
        // Never evict the key we just touched — the old loop would drain the
        // whole LRU and delete the current lookup once bulk SST keys filled the map.
        while (this.keys.size > keep && this.#keyAccessOrder.length > 1) {
            this.#dropKey(this.#keyAccessOrder.shift());
        }
        if (this.keys.size <= this.#maxKeysInMemory) {
            return;
        }
        const retain = new Set(this.#keyAccessOrder);
        for (const key of [...this.keys.keys()]) {
            if (!retain.has(key)) {
                this.#dropKey(key);
            }
        }
        this.#markFilesUnloaded();
    }
    /**
     * Track key access for LRU eviction.
     */
    #trackKeyAccess(key) {
        if (!this.#isLazyMode) {
            return;
        }
        // Remove from old position if it exists
        const existingIndex = this.#keyAccessOrder.indexOf(key);
        if (existingIndex >= 0) {
            this.#keyAccessOrder.splice(existingIndex, 1);
        }
        // Add to end (most recently used)
        this.#keyAccessOrder.push(key);
        this.#loadedKeys.add(key);
        // Periodically evict old keys
        if (this.keys.size > this.#maxKeysInMemory) {
            this.#evictKeysIfNeeded();
        }
    }
    /**
     * Get a key's value, loading the containing file if necessary (lazy mode).
     * In non-lazy mode, this is a simple map lookup.
     *
     * @param key The key to retrieve
     * @returns The LevelKeyValue, false (if deleted), or undefined (if not found)
     */
    async getKey(key) {
        // Check if already in memory
        if (this.keys.has(key)) {
            this.#trackKeyAccess(key);
            const cached = this.keys.get(key);
            if (cached !== undefined) {
                return cached;
            }
        }
        // In non-lazy mode, if not in keys, it doesn't exist
        if (!this.#isLazyMode || !this.#index) {
            return undefined;
        }
        // Lazy mode: find and load files that might contain this key.
        // Already-loaded files can still miss after LRU eviction, so re-read those.
        const take = () => {
            this.#trackKeyAccess(key);
            return this.keys.get(key);
        };
        const potentialFiles = this.#index.findPotentialFilesForKey(key);
        const stale = potentialFiles.filter((fileIdx) => fileIdx.isLoaded);
        for (const fileIdx of potentialFiles) {
            if (!fileIdx.isLoaded) {
                await this.loadFile(fileIdx);
            }
            if (this.keys.has(key)) {
                const entry = take();
                if (entry !== undefined) {
                    return entry;
                }
            }
        }
        for (const fileIdx of stale) {
            fileIdx.isLoaded = false;
            await this.loadFile(fileIdx);
            if (this.keys.has(key)) {
                const entry = take();
                if (entry !== undefined) {
                    return entry;
                }
            }
        }
        // Key not found in any file
        return undefined;
    }
    /**
     * Clear all loaded keys and reset to just the index metadata.
     * Useful for freeing memory after processing a world.
     */
    clearLoadedKeys() {
        for (const [, value] of this.keys) {
            // value can be LevelKeyValue, false, or undefined
            if (value && typeof value !== "boolean") {
                value.clearAllData();
            }
        }
        this.keys.clear();
        this.#keyAccessOrder = [];
        this.#loadedKeys.clear();
        // Reset file loaded flags so they can be reloaded on demand
        if (this.#index) {
            for (const fileIdx of this.#index.ldbFileIndexes) {
                fileIdx.isLoaded = false;
            }
            for (const fileIdx of this.#index.logFileIndexes) {
                fileIdx.isLoaded = false;
            }
        }
    }
    parseLdbContent(content, context, visitorState) {
        let keysParsed = 0;
        // Ends with magic: fixed64;
        // == 0xdb4775248b80fb57 (little-endian)
        if (content.length <= 8 ||
            content[content.length - 8] !== 87 ||
            content[content.length - 7] !== 251 ||
            content[content.length - 6] !== 128 ||
            content[content.length - 5] !== 139 ||
            content[content.length - 4] !== 36 ||
            content[content.length - 3] !== 117 ||
            content[content.length - 2] !== 71 ||
            content[content.length - 1] !== 219) {
            this.#pushError("Unexpected bytes in LDB file. File seems unreadable.", context);
            return;
        }
        // https://github.com/google/leveldb/blob/main/doc/table_format.md
        let index = content.length - 48;
        const metaIndexOffset = new Varint(content, index);
        index += metaIndexOffset.byteLength;
        const metaIndexSize = new Varint(content, index);
        index += metaIndexSize.byteLength;
        const indexOffset = new Varint(content, index);
        index += indexOffset.byteLength;
        const indexSize = new Varint(content, index);
        if (indexOffset.value <= 0 || indexOffset.value + indexSize.value >= content.length) {
            this.#pushError("LDB content index offset not within bounds.", context);
            return false;
        }
        if (metaIndexOffset.value <= 0 || metaIndexOffset.value + metaIndexSize.value >= content.length) {
            this.#pushError("LDB meta index offset not within bounds.", context);
            return false;
        }
        const indexContentCompressed = content.subarray(indexOffset.value, indexOffset.value + indexSize.value);
        let indexContent;
        // I believe this logic replicates: `https://twitter.com/_tomcc/status/894294552084860928`
        indexContent = this.#tryInflate(indexContentCompressed, true);
        if (!indexContent) {
            indexContent = this.#tryInflate(indexContentCompressed, false);
        }
        if (!indexContent) {
            indexContent = indexContentCompressed;
            // this._pushError("Treating level DB content as compressed.", context);
        }
        if (indexContent) {
            const indexKeys = {};
            if (!this.parseIndexBytes(indexContent, 0, indexContent.length, indexKeys, context)) {
                return false;
            }
            for (const lastKeyInBlock in indexKeys) {
                const indexKey = indexKeys[lastKeyInBlock];
                if (indexKey && indexKey.value) {
                    const indexBytes = indexKey.value;
                    let indexByteIndex = 0;
                    const blockOffset = new Varint(indexBytes, indexByteIndex);
                    indexByteIndex += blockOffset.byteLength;
                    const blockSize = new Varint(indexBytes, indexByteIndex);
                    indexByteIndex += blockSize.byteLength;
                    if (blockOffset.value < 0 || blockOffset.value + blockSize.value > content.length) {
                        this.#pushError("Block offset does not appear correct", context);
                        return;
                    }
                    // Newer Bedrock tables pad BlockHandles with extra checksum bytes.
                    // Older worlds have an exact varint pair; leftover here is fine.
                    const blockContentCompressed = content.subarray(blockOffset.value, blockOffset.value + blockSize.value);
                    let blockContent;
                    blockContent = this.#tryInflate(blockContentCompressed, true);
                    if (!blockContent) {
                        blockContent = this.#tryInflate(blockContentCompressed, false);
                    }
                    if (!blockContent) {
                        blockContent = blockContentCompressed;
                    }
                    keysParsed += this.parseLdbBlockBytes(blockContent, 0, blockContent.length, context, visitorState);
                }
                else {
                    this.#pushError("Could not find index key.", context);
                }
            }
        }
        if (keysParsed === 0) {
            this.#pushError("No keys found in LDB.", context);
        }
        return keysParsed;
    }
    parseIndexBytes(data, offset, length, indexKeys, context) {
        let index = offset;
        let lastKeyValuePair = undefined;
        const restarts = DataUtilities.getUnsignedInteger(data[length - 4], data[length - 3], data[length - 2], data[length - 1], true);
        const endRestartSize = restarts * 4 + 4;
        while (index < offset + length - endRestartSize) {
            const lb = new LevelKeyValue();
            lb.loadFromLdb(data, index, lastKeyValuePair);
            const key = lb.key;
            lastKeyValuePair = lb;
            if (Utilities.isUsableAsObjectKey(key)) {
                indexKeys[key] = lb;
            }
            if (lb.length === undefined) {
                this.#pushError("Unexpected parse of level key value " + key, context);
                return false;
            }
            index += lb.length;
        }
        return true;
    }
    parseLdbBlockBytes(data, offset, length, context, visitorState) {
        let index = offset;
        let keysParsed = 0;
        let lastKeyValuePair = undefined;
        const restarts = DataUtilities.getUnsignedInteger(data[length - 4], data[length - 3], data[length - 2], data[length - 1], true);
        const endRestartSize = restarts * 4 + 4;
        if (endRestartSize > offset + length) {
            this.#pushError("Unexpected size received for LDB bytes. File could be corrupt.", context);
            return 0;
        }
        while (index < offset + length - endRestartSize) {
            const lb = new LevelKeyValue();
            lb.loadFromLdb(data, index, lastKeyValuePair);
            const key = lb.key;
            lastKeyValuePair = lb;
            if (Utilities.isUsableAsObjectKey(key)) {
                if (visitorState) {
                    const keyBytes = lb.keyBytes;
                    if (keyBytes) {
                        visitorState.visitor({
                            ordinal: visitorState.ordinal++,
                            key: key,
                            keyBytes: keyBytes,
                            value: visitorState.options.includeValues ? lb.value : undefined,
                            sourceKind: visitorState.sourceKind,
                            sourcePath: visitorState.sourcePath
                        });
                    }
                }
                else {
                    this.keys.set(key, lb);
                }
            }
            if (lb.length === undefined || lb.length < 0) {
                throw new Error(this.#pushError("Unexpected parse of key " + key, context));
            }
            keysParsed++;
            index += lb.length;
        }
        return keysParsed;
    }
    parseLogContent(content, context, visitorState) {
        let index = 0;
        let pendingBytes = undefined;
        let keysParsed = 0;
        // https://github.com/google/leveldb/blob/main/doc/log_format.md
        while (index < content.length - 6) {
            /*const checksum = DataUtilities.getUnsignedInteger(
                content[index],
                content[index + 1],
                content[index + 2],
                content[index + 3],
                true
            );*/
            const length = DataUtilities.getUnsignedShort(content[index + 4], content[index + 5], true);
            const type = content[index + 6];
            index += 7; // size of record header
            if (type === 1 /* Type 1 = FULL */) {
                keysParsed += this.addValueFromLog(content, index, length, context, visitorState);
            }
            else if (type === 2 /* Type 2 = FIRST */) {
                pendingBytes = new Uint8Array(content.buffer, index, length);
            }
            else if (type === 3 /* Type 3 = MIDDLE */ || type === 4 /* Type 4 = LAST*/) {
                if (pendingBytes !== undefined) {
                    const appendBytes = new Uint8Array(content.buffer, index, length);
                    const newBytes = new Uint8Array(pendingBytes.byteLength + appendBytes.byteLength);
                    newBytes.set(pendingBytes);
                    newBytes.set(appendBytes, pendingBytes.byteLength);
                    pendingBytes = newBytes;
                    if (type === 4 /* This is the last part of a record */) {
                        keysParsed += this.addValueFromLog(pendingBytes, 0, pendingBytes.length, context, visitorState);
                    }
                }
                else {
                    this.#pushError("Unexpected middle to a set of bytes found within LevelDB content. File seems unreadable.", context);
                    return;
                }
            }
            else {
                this.#pushError("Unexpected type for log file. File seems unreadable.", context);
                return;
            }
            index += length;
            // new records don't start within 6 bytes of the end of a 32K block
            // Per docs: "A record never starts within the last six bytes of a [32K] block (since it won't fit). Any
            // leftover bytes here form the trailer, which must consist entirely of zero bytes and must be skipped by readers."
            let bytesFromEndOfBlock = 32768 - (index % 32768);
            while (bytesFromEndOfBlock <= 6 && bytesFromEndOfBlock > 0) {
                bytesFromEndOfBlock--;
                if (content[index] !== 0) {
                    this.#pushError("Unexpectedly found a padding trailer with data", context);
                }
                index++;
            }
        }
        if (keysParsed <= 0) {
            this.#pushError("Did not find any keys in log file", context);
        }
        return keysParsed;
    }
    addValueFromLog(content, index, length, context, visitorState) {
        const startIndex = index;
        // first 8 bytes are sequence number; next 4 are record count; skip over those for now.
        index += 12;
        let keysParsed = 0;
        while (index <= startIndex + length - 5) {
            const isLive = content[index];
            index++;
            const keyLength = new Varint(content, index);
            index += keyLength.byteLength;
            const keyBytes = new Uint8Array(keyLength.value);
            for (let i = 0; i < keyLength.value; i++) {
                keyBytes[i] = content[index + i];
            }
            index += keyLength.value;
            if (index > content.length) {
                this.#pushError("Unexpected log file length issue.", context);
            }
            if (index <= content.length) {
                const key = Utilities.getAsciiStringFromUint8Array(keyBytes);
                if (key === undefined) {
                    this.#pushError("Unexpected empty key in a log file. File could be unreadable.", context);
                }
                keysParsed++;
                if (isLive) {
                    if (index >= content.length) {
                        this.#pushError("Unexpectedly leftover content in a log file. File could be unreadable.", context);
                    }
                    const dataLength = new Varint(content, index);
                    index += dataLength.byteLength;
                    if (dataLength.value + index <= content.buffer.byteLength) {
                        const valueStartIndex = index;
                        index += dataLength.value;
                        if (Utilities.isUsableAsObjectKey(key)) {
                            if (visitorState) {
                                let data;
                                if (visitorState.options.includeValues) {
                                    data = content.slice(valueStartIndex, valueStartIndex + dataLength.value);
                                }
                                visitorState.visitor({
                                    ordinal: visitorState.ordinal++,
                                    key: key,
                                    keyBytes: keyBytes,
                                    value: visitorState.options.includeValues ? data : undefined,
                                    sourceKind: visitorState.sourceKind,
                                    sourcePath: visitorState.sourcePath
                                });
                            }
                            else {
                                // slice() (not subarray / new Uint8Array(content.buffer, ...))
                                // makes a tightly-sized copy with its own ArrayBuffer, so V8 can
                                // GC each log-file buffer as keys become unreachable. A view
                                // would pin the whole multi-MB log file alive — see the
                                // memory-retention note in LevelKeyValue.loadFromLdb.
                                const data = content.slice(valueStartIndex, valueStartIndex + dataLength.value);
                                const kv = new LevelKeyValue();
                                kv.sharedKey = "";
                                kv.keyDelta = key;
                                kv.unsharedKeyBytes = keyBytes;
                                kv.value = data;
                                this.keys.set(key, kv);
                            }
                        }
                    }
                }
                else {
                    if (Utilities.isUsableAsObjectKey(key)) {
                        if (visitorState) {
                            if (visitorState.options.includeDeleted) {
                                visitorState.visitor({
                                    ordinal: visitorState.ordinal++,
                                    key: key,
                                    keyBytes: keyBytes,
                                    isDeleted: true,
                                    sourceKind: visitorState.sourceKind,
                                    sourcePath: visitorState.sourcePath
                                });
                            }
                        }
                        else {
                            this.keys.set(key, false);
                        }
                    }
                }
            }
        }
        return keysParsed;
    }
    parseManifestContent(content, context) {
        let index = 0;
        let pendingBytes = undefined;
        this.comparator = undefined;
        this.logNumber = undefined;
        this.nextFileNumber = undefined;
        this.lastSequence = undefined;
        this.compactPointerLevels = undefined;
        this.compactPointerStrings = undefined;
        this.deletedFileLevel = undefined;
        this.deletedFileNumber = undefined;
        this.newFileLevel = undefined;
        this.newFileNumber = undefined;
        this.newFileSize = undefined;
        this.newFileSmallest = undefined;
        this.newFileLargest = undefined;
        // https://github.com/google/leveldb/blob/main/doc/log_format.md
        while (index < content.length - 6) {
            /*const checksum = DataUtilities.getUnsignedInteger(
                content[index],
                content[index + 1],
                content[index + 2],
                content[index + 3],
                true
            );*/
            const length = DataUtilities.getUnsignedShort(content[index + 4], content[index + 5], true);
            const type = content[index + 6];
            index += 7; // size of record header
            if (type === 1 /* Type 1 = FULL */) {
                this.addValueFromManifest(content, index, length);
            }
            else if (type === 2 /* Type 2 = FIRST */) {
                pendingBytes = new Uint8Array(content.buffer, index, length);
            }
            else if (type === 3 /* Type 3 = MIDDLE */ || type === 4 /* Type 4 = LAST*/) {
                if (pendingBytes !== undefined) {
                    const appendBytes = new Uint8Array(content.buffer, index, length);
                    const newBytes = new Uint8Array(pendingBytes.byteLength + appendBytes.byteLength);
                    newBytes.set(pendingBytes);
                    newBytes.set(appendBytes, pendingBytes.byteLength);
                    pendingBytes = newBytes;
                    if (type === 4 /* This is the last part of a record */) {
                        this.addValueFromManifest(pendingBytes, 0, pendingBytes.length);
                    }
                }
                else {
                    this.#pushError("Unexpected middle to a set of bytes found within a manifest file. File could be unreadable.", context);
                    return;
                }
            }
            else {
                this.#pushError("Unexpected type for manifest file. File could be unreadable.", context);
                return;
            }
            index += length;
            // new records don't start within 6 bytes of the end of a 32K block
            // Per docs: "A record never starts within the last six bytes of a [32K] block (since it won't fit). Any
            // leftover bytes here form the trailer, which must consist entirely of zero bytes and must be skipped by readers."
            let bytesFromEndOfBlock = 32768 - (index % 32768);
            while (bytesFromEndOfBlock <= 6 && bytesFromEndOfBlock > 0) {
                bytesFromEndOfBlock--;
                if (content[index] !== 0) {
                    this.#pushError("Unexpectedly found a padding trailer with data in a manifest file.", context);
                }
                index++;
            }
        }
    }
    addValueFromManifest(content, index, length, context) {
        const startIndex = index;
        // https://github.com/google/leveldb/blob/main/db/version_edit.cc
        while (index < startIndex + length) {
            const tag = new Varint(content, index);
            index += tag.byteLength;
            switch (tag.value) {
                case 1: // comparator
                    const comparatorPrefixedSliceLength = new Varint(content, index);
                    index += comparatorPrefixedSliceLength.byteLength;
                    // comparator prefixed slice
                    const comparatorBytes = new Uint8Array(comparatorPrefixedSliceLength.value);
                    for (let i = 0; i < comparatorPrefixedSliceLength.value; i++) {
                        comparatorBytes[i] = content[index + i];
                    }
                    index += comparatorPrefixedSliceLength.value;
                    if (index > content.length) {
                        this.#pushError("Unexpected manifest file length issue.", context);
                    }
                    this.comparator = Utilities.getAsciiStringFromUint8Array(comparatorBytes);
                    if (this.comparator === undefined) {
                        this.#pushError("Unexpected comparator.", context);
                    }
                    break;
                case 2: // logNumber
                    const logNumberVarint = new Varint(content, index);
                    index += logNumberVarint.byteLength;
                    this.logNumber = logNumberVarint.value;
                    break;
                case 3: // nextFileNumber
                    const nextFileNumberVarint = new Varint(content, index);
                    index += nextFileNumberVarint.byteLength;
                    this.nextFileNumber = nextFileNumberVarint.value;
                    break;
                case 4: // lastSequence
                    const lastSequenceVarint = new Varint(content, index);
                    index += lastSequenceVarint.byteLength;
                    this.lastSequence = lastSequenceVarint.value;
                    break;
                case 5: // compactPointer
                    if (this.compactPointerLevels === undefined) {
                        this.compactPointerLevels = [];
                    }
                    if (this.compactPointerStrings === undefined) {
                        this.compactPointerStrings = [];
                    }
                    const compactPointerLevel = new Varint(content, index);
                    index += compactPointerLevel.byteLength;
                    this.compactPointerLevels.push(compactPointerLevel.value);
                    const compactPointerStrLength = new Varint(content, index);
                    index += compactPointerStrLength.byteLength;
                    // comparator prefixed slice
                    const compactPointerStrBytes = new Uint8Array(compactPointerStrLength.value);
                    for (let i = 0; i < compactPointerStrLength.value; i++) {
                        compactPointerStrBytes[i] = content[index + i];
                    }
                    index += compactPointerStrLength.value;
                    if (index > content.length) {
                        this.#pushError("Unexpected manifest file length issue at compact pointer.", context);
                    }
                    this.compactPointerStrings.push(Utilities.getAsciiStringFromUint8Array(compactPointerStrBytes));
                    if (this.compactPointerStrings[this.compactPointerStrings.length - 1] === undefined) {
                        this.#pushError("Unexpected compact pointer string.", context);
                    }
                    break;
                case 6: // deletedFile
                    if (this.deletedFileLevel === undefined) {
                        this.deletedFileLevel = [];
                    }
                    if (this.deletedFileNumber === undefined) {
                        this.deletedFileNumber = [];
                    }
                    const deletedFileLevel = new Varint(content, index);
                    index += deletedFileLevel.byteLength;
                    this.deletedFileLevel.push(deletedFileLevel.value);
                    const deletedFileNumber = new Varint(content, index);
                    index += deletedFileNumber.byteLength;
                    this.deletedFileNumber.push(deletedFileNumber.value);
                    break;
                case 7: // newFile
                    if (this.newFileLargest === undefined) {
                        this.newFileLargest = [];
                    }
                    if (this.newFileLevel === undefined) {
                        this.newFileLevel = [];
                    }
                    if (this.newFileNumber === undefined) {
                        this.newFileNumber = [];
                    }
                    if (this.newFileSmallest === undefined) {
                        this.newFileSmallest = [];
                    }
                    if (this.newFileSize === undefined) {
                        this.newFileSize = [];
                    }
                    const newFileLevel = new Varint(content, index);
                    index += newFileLevel.byteLength;
                    this.newFileLevel.push(newFileLevel.value);
                    const newFileNumber = new Varint(content, index);
                    index += newFileNumber.byteLength;
                    this.newFileNumber.push(newFileNumber.value);
                    const newFileSize = new Varint(content, index);
                    index += newFileSize.byteLength;
                    this.newFileSize.push(newFileSize.value);
                    const newFileSmallestStrLength = new Varint(content, index);
                    index += newFileSmallestStrLength.byteLength;
                    const newFileSmallestStrBytes = new Uint8Array(newFileSmallestStrLength.value);
                    for (let i = 0; i < newFileSmallestStrLength.value; i++) {
                        newFileSmallestStrBytes[i] = content[index + i];
                    }
                    index += newFileSmallestStrLength.value;
                    if (index > content.length) {
                        this.#pushError("Unexpected manifest file length issue at new file smallest.", context);
                    }
                    this.newFileSmallest.push(Utilities.getAsciiStringFromUint8Array(newFileSmallestStrBytes));
                    if (this.newFileSmallest[this.newFileSmallest.length - 1] === undefined) {
                        this.#pushError("Unexpected file smallest tag string.", context);
                    }
                    const newFileLargestStrLength = new Varint(content, index);
                    index += newFileLargestStrLength.byteLength;
                    const newFileLargestStrBytes = new Uint8Array(newFileLargestStrLength.value);
                    for (let i = 0; i < newFileLargestStrLength.value; i++) {
                        newFileLargestStrBytes[i] = content[index + i];
                    }
                    index += newFileLargestStrLength.value;
                    if (index > content.length) {
                        this.#pushError("Unexpected manifest file length issue at new file largest.", context);
                    }
                    this.newFileLargest.push(Utilities.getAsciiStringFromUint8Array(newFileLargestStrBytes));
                    if (this.newFileLargest[this.newFileLargest.length - 1] === undefined) {
                        this.#pushError("Unexpected file largest tag string.", context);
                    }
                    break;
                case 9: // previousLogNumber
                    const prevLogNumber = new Varint(content, index);
                    index += prevLogNumber.byteLength;
                    this.previousLogNumber = prevLogNumber.value;
                    break;
                default:
                    this.#pushError("Unexpected manifest item: " + tag.value, context);
            }
        }
    }
}
