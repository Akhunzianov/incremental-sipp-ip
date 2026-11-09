// Test-only adapter for the UNMODIFIED pinned authors' implementation.
#define main upstream_main
#include "../vendor/sipp-ip/src/SIPP-IP.cpp"
#undef main
int main() {
    std::ios::sync_with_stdio(false);
    fillActions();
    int h,w;
    while(std::cin>>h>>w) {
        int horizon,sr,sc,so,sv,start,gv; long long budget;
        std::cin>>horizon>>sr>>sc>>so>>sv>>start>>end_x>>end_y>>gv>>budget;
        if(h>MXH || w>MXW || horizon>=INF-1 || sv!=0) return 2;
        clr(); H=h; W=w; end_v=gv;
        std::vector<std::string> grid(h);
        std::vector<std::vector<std::pair<int,int>>> blocks(h*w);
        for(int r=0;r<h;++r) {
            std::cin>>grid[r];
            for(int c=0;c<w;++c) if(grid[r][c]=='#') blocks[r*w+c].push_back({0,INF});
        }
        int count; std::cin>>count;
        for(int i=0;i<count;++i) {
            int r,c,a,b; std::cin>>r>>c>>a>>b; blocks[r*w+c].push_back({a,b});
        }
        bool invalid=false;
        for(int r=0;r<h;++r) for(int c=0;c<w;++c) {
            auto& bs=blocks[r*w+c]; bs.push_back({horizon+1,INF});
            std::sort(bs.begin(),bs.end());
            std::vector<std::pair<int,int>> merged;
            for(auto [a,b]:bs) {
                if(merged.empty() || a>merged.back().second+1) merged.push_back({a,b});
                else merged.back().second=std::max(merged.back().second,b);
            }
            for(auto [a,b]:merged) {
                rsrv_tbl[r][c].insert({a,b});
                if(r==sr && c==sc && a<=start && start<=b) invalid=true;
            }
        }
        if(invalid) { std::cout<<"{\"status\":\"invalid_start\",\"cost_ticks\":null}\n"; continue; }
        auto answer=search(sr,sc,so,sv,start);
        if(answer.second) std::cout<<"{\"status\":\"solved\",\"cost_ticks\":"<<CLOSED_vec[answer.first].t_lower<<"}\n";
        else std::cout<<"{\"status\":\"no_path\",\"cost_ticks\":null}\n";
    }
}
