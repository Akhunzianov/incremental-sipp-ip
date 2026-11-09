#pragma once
#include "model.hpp"

// Each ordinary expansion emits a contiguous range of child nodes, including
// an empty range when all outgoing actions fail. Only the last search is kept.
struct ExpansionCache {
    struct Record { int lo,hi,first,last,next; };
    std::vector<int> heads;
    std::vector<Record> records;
    std::vector<Node> children;

    void record(int key,int lo,int hi,int first,int last) {
        int id=static_cast<int>(records.size());
        records.push_back({lo,hi,first,last,heads[key]});
        heads[key]=id;
    }
    const Record* containing(int key,int lo,int hi) const {
        for(int i=heads[key];i>=0;i=records[i].next) {
            const auto& r=records[i];
            if(r.lo<=lo && hi<=r.hi) return &r;
        }
        return nullptr;
    }
};
